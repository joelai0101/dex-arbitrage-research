#include "paper_batch_layerwise_model.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <optional>
#include <stdexcept>
#include <tuple>

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

std::optional<std::size_t> earliest_scheduled_edge(
    const std::vector<VertexId> &path,
    const std::map<DirectedEdge, std::size_t> &schedule_rank) {
  std::optional<std::size_t> earliest;
  for (std::size_t index = 0; index + 1 < path.size(); ++index) {
    const auto found = schedule_rank.find({path[index], path[index + 1]});
    if (found != schedule_rank.end() &&
        (!earliest.has_value() || found->second < *earliest)) {
      earliest = found->second;
    }
  }
  return earliest;
}

std::optional<StateValue> recompute_state(const DirectedWeightedGraph &graph,
                                          const ColorMap &colors,
                                          std::uint32_t hop_bound,
                                          const StateTable &states,
                                          const StateKey &key) {
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
    const ColorMask predecessor_bit = color_bit(colors, predecessor, hop_bound);
    if ((predecessor_mask & predecessor_bit) == 0) {
      continue;
    }
    const auto found = states.find({key.source, predecessor, predecessor_mask});
    if (found == states.end() || found->second.path.empty() ||
        found->second.path.front() != key.source ||
        found->second.path.back() != predecessor) {
      continue;
    }
    StateValue candidate = found->second;
    candidate.weight += edge_weight;
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
  result.schedule = build_schedule(updates, graph_.edges(), mode, policy);
  result.cross_dag_vertex_overlap =
      has_cross_dag_vertex_overlap(result.schedule.dags);

  std::map<DirectedEdge, EdgeUpdate> effective_updates;
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

  std::vector<std::set<StateKey>> pending(hop_bound_ + 1);
  std::set<StateKey> ever_queued;
  auto enqueue = [&](const StateKey &key) {
    const std::size_t layer = popcount(key.colors);
    if (layer < 2 || layer > hop_bound_) {
      return false;
    }
    const bool inserted = pending[layer].insert(key).second;
    if (inserted && ever_queued.insert(key).second) {
      ++result.queued_state_keys;
    }
    return inserted;
  };

  // Preserve the Algorithm 3 forward order inside each source bucket.  A
  // forward apply seeds every existing prefix that can legally append the
  // updated edge.  The state itself is recomputed later from all alternatives.
  std::map<VertexId, std::vector<DirectedEdge>> forward_by_source;
  for (const DirectedEdge &edge : result.forward_applied_updates) {
    if (graph_.has_edge(edge.source, edge.destination)) {
      forward_by_source[edge.source].push_back(edge);
    }
  }

  std::map<DirectedEdge, std::size_t> backward_rank;
  for (std::size_t index = 0; index < result.backward_applied_updates.size();
       ++index) {
    backward_rank.emplace(result.backward_applied_updates[index], index);
  }
  std::vector<std::vector<StateKey>> backward_seed_buckets(
      result.backward_applied_updates.size());

  // One table scan implements both paper directions without multiplying the
  // scan cost by batch size.  Forward seeds possible new/better paths;
  // backward invalidates currently selected witnesses that contain a changed
  // edge (the missing increase/delete rule in the paper pseudocode).
  for (const auto &[key, value] : states_) {
    const auto backward_position =
        earliest_scheduled_edge(value.path, backward_rank);
    if (backward_position.has_value()) {
      backward_seed_buckets[*backward_position].push_back(key);
    }
    const auto outgoing_updates = forward_by_source.find(key.destination);
    if (outgoing_updates == forward_by_source.end()) {
      continue;
    }
    for (const DirectedEdge &edge : outgoing_updates->second) {
      const ColorMask destination_bit =
          color_bit(colors_, edge.destination, hop_bound_);
      if ((key.colors & destination_bit) != 0) {
        continue;
      }
      if (enqueue(
              {key.source, edge.destination, key.colors | destination_bit})) {
        ++result.forward_candidate_seeds;
      }
    }
  }
  // Feed invalidation seeds to the DP queue in the exact reverse-topological
  // update-edge order generated above.  A state depending on several updated
  // edges is attached to the earliest backward apply and still queued once.
  for (const auto &bucket : backward_seed_buckets) {
    for (const StateKey &key : bucket) {
      ++result.backward_invalidation_seeds;
      enqueue(key);
    }
  }

  std::set<StateKey> processed;
  for (std::size_t layer = 2; layer <= hop_bound_; ++layer) {
    for (const StateKey &key : pending[layer]) {
      if (!processed.insert(key).second) {
        throw std::runtime_error(
            "a DP state was processed more than once in one layer-wise pass");
      }
      ++result.processed_state_keys;
      const auto old = states_.find(key);
      const std::optional<StateValue> replacement =
          recompute_state(graph_, colors_, hop_bound_, states_, key);

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
      for (const auto &[next, ignored_weight] :
           graph_.outgoing(key.destination)) {
        (void)ignored_weight;
        const ColorMask next_bit = color_bit(colors_, next, hop_bound_);
        if ((key.colors & next_bit) == 0) {
          enqueue({key.source, next, key.colors | next_bit});
        }
      }
    }
  }

  result.every_state_processed_at_most_once =
      processed.size() == result.processed_state_keys &&
      result.processed_state_keys == result.queued_state_keys;
  if (!result.every_state_processed_at_most_once) {
    throw std::runtime_error(
        "layer-wise state queue left an unprocessed or duplicate state");
  }
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
