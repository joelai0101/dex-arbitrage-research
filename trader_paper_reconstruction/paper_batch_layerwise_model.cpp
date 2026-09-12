#include "paper_batch_layerwise_model.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <optional>
#include <stdexcept>
#include <tuple>
#ifdef TRADER_PROFILE
#include <chrono>
#endif

namespace trader::paper_batch {
namespace {

std::size_t popcount(ColorMask mask) {
  std::size_t result = 0;
  while (mask != 0) {
    result += static_cast<std::size_t>(mask & ColorMask{1});
    mask >>= 1U;
  }
  return result;
}

ColorMask color_bit(const ColorMap &colors, VertexId vertex,
                    std::uint32_t hop_bound) {
  const auto found = colors.find(vertex);
  if (found == colors.end() || found->second >= hop_bound || hop_bound == 0 ||
      hop_bound > 63) {
    throw std::invalid_argument(
        "fixed color map does not cover a graph vertex");
  }
  return ColorMask{1} << found->second;
}

void validate(const DirectedWeightedGraph &graph, const ColorMap &colors,
              std::uint32_t hop_bound) {
  if (hop_bound < 2 || hop_bound > 63) {
    throw std::invalid_argument("hop_bound must be between 2 and 63");
  }
  for (const VertexId vertex : graph.vertices()) {
    (void)color_bit(colors, vertex, hop_bound);
  }
}

bool same_state_value(const StateValue &left, const StateValue &right) {
  return left.weight == right.weight && left.path == right.path;
}

bool better_candidate(const StateValue &candidate, const StateValue &current) {
  return candidate.weight < current.weight ||
         (candidate.weight == current.weight && candidate.path < current.path);
}

std::optional<StateValue> recompute_state(const DirectedWeightedGraph &graph,
                                          const ColorMap &colors,
                                          std::uint32_t hop_bound,
                                          const StateTable &states,
                                          const StateKey &key
#ifdef TRADER_PROFILE
                                          , LayerwiseBatchApplication &profile
#endif
                                          ) {
  const ColorMask destination_bit =
      color_bit(colors, key.destination, hop_bound);
  if ((key.colors & destination_bit) == 0 || popcount(key.colors) < 2 ||
      popcount(key.colors) > hop_bound) {
    return std::nullopt;
  }

  const ColorMask predecessor_mask = key.colors & ~destination_bit;
  std::optional<StateValue> best;
  for (const auto &[predecessor, edge_weight] :
       graph.incoming(key.destination)) {
#ifdef TRADER_PROFILE
    ++profile.incoming_edges_scanned;
#endif
    const ColorMask predecessor_bit = color_bit(colors, predecessor, hop_bound);
    if ((predecessor_mask & predecessor_bit) == 0) {
      continue;
    }
#ifdef TRADER_PROFILE
    ++profile.incoming_state_lookups;
#endif
    const auto found = states.find({key.source, predecessor, predecessor_mask});
    if (found == states.end() || found->second.path.empty() ||
        found->second.path.front() != key.source ||
        found->second.path.back() != predecessor) {
      continue;
    }
    const double weight = found->second.weight + edge_weight;
    if (best && weight > best->weight) continue;
    StateValue candidate{weight, {}};
    candidate.path.reserve(found->second.path.size() + 1);
    candidate.path.insert(candidate.path.end(), found->second.path.begin(), found->second.path.end());
    candidate.path.push_back(key.destination);
    if (!best.has_value() || better_candidate(candidate, *best)) {
      best = std::move(candidate);
    }
  }
  return best;
}

} // namespace

PaperLayerwiseBatchMaintainer::PaperLayerwiseBatchMaintainer(
    DirectedWeightedGraph graph, ColorMap colors, std::uint32_t hop_bound)
    : graph_(std::move(graph)), colors_(std::move(colors)),
      hop_bound_(hop_bound) {
  validate(graph_, colors_, hop_bound_);
  states_ = build_static_dp(graph_, colors_, hop_bound_);
}

LayerwiseBatchApplication PaperLayerwiseBatchMaintainer::apply_batch(
    const std::vector<EdgeUpdate> &updates, DependencyGraphMode mode) {
  return apply_batch(updates, mode, SchedulePolicy{});
}

LayerwiseBatchApplication PaperLayerwiseBatchMaintainer::apply_batch(
    const std::vector<EdgeUpdate> &updates, DependencyGraphMode mode,
    const SchedulePolicy &policy) {
  LayerwiseBatchApplication result;
#ifdef TRADER_PROFILE
  using Clock = std::chrono::steady_clock;
  const auto profile_started = Clock::now();
#endif
  result.schedule = build_schedule(updates, graph_.edges(), mode, policy);
  result.cross_dag_vertex_overlap =
      has_cross_dag_vertex_overlap(result.schedule.dags);

  std::map<DirectedEdge, EdgeUpdate> effective_updates;
  std::set<DirectedEdge> adverse_edges;
  for (const EdgeUpdate &update : result.schedule.coalesced_updates) {
    const DirectedEdge edge{update.source, update.destination};
    const std::optional<double> old_weight =
        graph_.edge_weight(update.source, update.destination);
    const bool effective =
        update.erase ? old_weight.has_value()
                     : !old_weight.has_value() || *old_weight != update.weight;
    if (!effective) {
      continue;
    }
    if (!update.erase && !std::isfinite(update.weight)) {
      throw std::invalid_argument(
          "finite edge write required; use erase for deletion");
    }
    effective_updates.emplace(edge, update);
    if (update.erase || (old_weight && update.weight > *old_weight))
      adverse_edges.insert(edge);
    result.effective_updates.push_back(edge);
  }

  // Algorithm 3's queues are constructed from the pre-batch graph, while all
  // DP state recomputation below reads one unambiguous batch-final snapshot.
  // This is the explicit atomic-batch rule used to resolve cross-DAG overlap.
  for (const auto &[edge, update] : effective_updates) {
    if (update.erase) {
      graph_.remove_edge(edge.source, edge.destination);
    } else {
      (void)color_bit(colors_, edge.source, hop_bound_);
      (void)color_bit(colors_, edge.destination, hop_bound_);
      graph_.set_edge(edge.source, edge.destination, update.weight);
    }
  }
  validate(graph_, colors_, hop_bound_);

  // Operation 1: a vertex first introduced by a finite edge receives its
  // zero-hop DP state before forward apply considers the edge.
  for (const VertexId vertex : graph_.vertices()) {
    const StateKey base{vertex, vertex, color_bit(colors_, vertex, hop_bound_)};
    states_.emplace(base, StateValue{0.0, {vertex}});
  }

  std::map<DirectedEdge, std::size_t> forward_counts;
  std::map<DirectedEdge, std::size_t> backward_counts;
  for (const Dag &dag : result.schedule.dags) {
    const auto forward = forward_edge_order(
        dag, result.schedule.dependency_edges, policy.topological_ties);
    for (const std::size_t edge_index : forward) {
      const DirectedEdge edge = result.schedule.dependency_edges.at(edge_index);
      if (effective_updates.count(edge) != 0) {
        result.forward_applied_updates.push_back(edge);
        ++forward_counts[edge];
      }
    }
    const auto backward = backward_edge_order(
        dag, result.schedule.dependency_edges, policy.topological_ties);
    for (const std::size_t edge_index : backward) {
      const DirectedEdge edge = result.schedule.dependency_edges.at(edge_index);
      if (effective_updates.count(edge) != 0) {
        result.backward_applied_updates.push_back(edge);
        ++backward_counts[edge];
      }
    }
  }

  result.effective_update_coverage =
      forward_counts.size() == effective_updates.size() &&
      backward_counts.size() == effective_updates.size();
  for (const auto &[edge, ignored] : effective_updates) {
    (void)ignored;
    result.effective_update_coverage = result.effective_update_coverage &&
                                       forward_counts[edge] == 1 &&
                                       backward_counts[edge] == 1;
  }
  if (!result.effective_update_coverage) {
    throw std::runtime_error("Algorithm 3 schedule did not apply each "
                             "effective update once per pass");
  }

#ifdef TRADER_PROFILE
  const auto profile_setup_end = Clock::now();
#endif
  struct PendingState {
    bool must_recompute = false;
    std::optional<StateValue> improvement;
  };
  // One ordered entry holds queue membership, invalidation and the best
  // proposal. Separate trees repeat the same keys and lookups.
  std::vector<std::map<StateKey, PendingState>> pending(hop_bound_ + 1);

  auto offer_improvement = [&](const StateKey &key, const StateValue &prefix,
                               double edge_weight) {
    const std::size_t layer = popcount(key.colors);
    if (layer < 2 || layer > hop_bound_) return false;
#ifdef TRADER_PROFILE
    ++result.proposal_attempts;
#endif
    const double weight = prefix.weight + edge_weight;
    const auto old = states_.find(key);
    if (old != states_.end() && weight > old->second.weight) return false;
    StateValue candidate{weight, {}};
    candidate.path.reserve(prefix.path.size() + 1);
    candidate.path.insert(candidate.path.end(), prefix.path.begin(), prefix.path.end());
    candidate.path.push_back(key.destination);
    if (old != states_.end() && !better_candidate(candidate, old->second)) return false;
    auto [entry, inserted] = pending[layer].try_emplace(key);
    if (inserted) ++result.queued_state_keys;
    auto &proposal = entry->second.improvement;
    if (!proposal || better_candidate(candidate, *proposal)) proposal = std::move(candidate);
    return inserted;
  };

  auto request_repair = [&](const StateKey &key, VertexId predecessor) {
    const std::size_t layer = popcount(key.colors);
    if (layer < 2 || layer > hop_bound_) return false;
#ifdef TRADER_PROFILE
    ++result.repair_requests;
#endif
    const auto uses_predecessor = [&](const StateValue &value) {
      return value.path.size() >= 2 &&
             value.path[value.path.size() - 2] == predecessor;
    };
    const auto current = states_.find(key);
    auto entry = pending[layer].find(key);
    // Worsening an unused recurrence contribution cannot worsen the optimum.
    // A mixed batch may nevertheless have queued a now-stale improvement,
    // including for a state that did not exist before this batch.
    if ((current == states_.end() || !uses_predecessor(current->second)) &&
        (entry == pending[layer].end() || !entry->second.improvement ||
         !uses_predecessor(*entry->second.improvement)))
      return false;
    if (entry != pending[layer].end()) {
      entry->second.must_recompute = true;
      return false;
    }
    pending[layer].emplace(key, PendingState{true, std::nullopt});
    ++result.queued_state_keys;
    return true;
  };

  // StateKey is destination-major: locate only prefixes ending at the
  // updated edge's source. No whole-table or stored-path scan is required.
  // Deletions must also seed the old recurrence contribution. Recompute the
  // successor from the final graph, then propagate changes one color layer
  // at a time; every longer witness using the edge depends on that successor.
  auto seed_edge = [&](const DirectedEdge &edge, bool repair) {
    const ColorMask bit = color_bit(colors_, edge.destination, hop_bound_);
    std::size_t inserted = 0;
    auto it = states_.lower_bound(StateKey{0, edge.source, 0});
    for (; it != states_.end() && it->first.destination == edge.source; ++it) {
#ifdef TRADER_PROFILE
      ++result.seed_prefixes_examined;
#endif
      const auto &key = it->first;
      if ((key.colors & bit) != 0) continue;
      const StateKey successor{key.source, edge.destination, key.colors | bit};
      if (repair) {
        if (request_repair(successor, edge.source)) ++inserted;
      } else if (offer_improvement(successor, it->second,
                                  *graph_.edge_weight(edge.source, edge.destination))) ++inserted;
    }
    return inserted;
  };
  for (const auto &edge : result.forward_applied_updates)
    if (!adverse_edges.count(edge)) result.forward_candidate_seeds += seed_edge(edge, false);
  for (const auto &edge : result.backward_applied_updates)
    if (adverse_edges.count(edge)) result.backward_invalidation_seeds += seed_edge(edge, true);

#ifdef TRADER_PROFILE
  const auto profile_seed_end = Clock::now();
#endif
  // A key belongs to exactly one color-cardinality layer, whose map already
  // deduplicates it. Propagation adds one color, so it cannot enqueue work in
  // this or an earlier layer. Separate ever-queued/processed trees duplicate
  // the same keys without strengthening this once-per-pass invariant.
  for (std::size_t layer = 2; layer <= hop_bound_; ++layer) {
    for (auto &[key, work] : pending[layer]) {
      ++result.processed_state_keys;
      const auto old = states_.find(key);
      // Only invalidated states need the full incoming-edge recurrence. For
      // insertions/decreases, unchanged predecessors cannot improve the old
      // optimum; incoming proposals carry every changed lower-layer value.
      // A repair wins over all possibly stale proposals in a mixed batch.
      std::optional<StateValue> replacement;
      if (work.must_recompute) {
#ifdef TRADER_PROFILE
        ++result.repair_states;
#endif
        replacement = recompute_state(graph_, colors_, hop_bound_, states_, key
#ifdef TRADER_PROFILE
                                      , result
#endif
                                      );
      } else {
#ifdef TRADER_PROFILE
        ++result.proposal_states;
#endif
        if (!work.improvement) throw std::runtime_error("missing queued improvement");
        replacement = std::move(*work.improvement);
        if (old != states_.end() && better_candidate(old->second, *replacement))
          replacement = old->second;
      }
      const bool invalidated = old != states_.end() &&
          (!replacement || better_candidate(old->second, *replacement));

      bool changed = false;
      if (!replacement.has_value()) {
        if (old != states_.end()) {
          states_.erase(old);
          changed = true;
          ++result.removed_state_keys;
        }
      } else if (old == states_.end()) {
        states_.emplace(key, *replacement);
        changed = true;
      } else if (!same_state_value(old->second, *replacement)) {
        old->second = *replacement;
        changed = true;
      }

      if (!changed) {
        continue;
      }
      ++result.changed_state_keys;
      if (layer == hop_bound_ && graph_.has_edge(key.destination, key.source))
        result.changed_closed_states.push_back({key.source, key.destination});
      for (const auto &[next, edge_weight] :
           graph_.outgoing(key.destination)) {
        const ColorMask next_bit = color_bit(colors_, next, hop_bound_);
        if ((key.colors & next_bit) == 0) {
          const StateKey successor{key.source, next, key.colors | next_bit};
          if (invalidated) {
            request_repair(successor, key.destination);
          } else if (replacement) {
            offer_improvement(successor, *replacement, edge_weight);
          }
        }
      }
    }
    // All descendants are in later layers; no future operation uses this
    // layer's proposals or repair flags. Release transient storage now.
    pending[layer].clear();
  }

  result.every_state_processed_at_most_once =
      result.processed_state_keys == result.queued_state_keys;
  if (!result.every_state_processed_at_most_once) {
    throw std::runtime_error(
        "layer-wise state queue left an unprocessed or duplicate state");
  }
#ifdef TRADER_PROFILE
  const auto profile_end = Clock::now();
  result.setup_ms = std::chrono::duration<double,std::milli>(profile_setup_end-profile_started).count();
  result.seed_ms = std::chrono::duration<double,std::milli>(profile_seed_end-profile_setup_end).count();
  result.propagation_ms = std::chrono::duration<double,std::milli>(profile_end-profile_seed_end).count();
#endif
  return result;
}

const DirectedWeightedGraph &PaperLayerwiseBatchMaintainer::graph() const {
  return graph_;
}

const StateTable &PaperLayerwiseBatchMaintainer::states() const {
  return states_;
}

const ColorMap &PaperLayerwiseBatchMaintainer::colors() const {
  return colors_;
}

std::uint32_t PaperLayerwiseBatchMaintainer::hop_bound() const {
  return hop_bound_;
}

CycleAnswer PaperLayerwiseBatchMaintainer::answer() const {
  return answer_from_dp(graph_, states_, hop_bound_);
}

} // namespace trader::paper_batch
