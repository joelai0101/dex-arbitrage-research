#include "paper_edge_grouping.h"
#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <stdexcept>
#ifdef TRADER_PROFILE
#include <chrono>
#endif

namespace trader::paper_batch {
namespace {
Cycle canonical(Cycle cycle) {
  cycle.pop_back();
  std::rotate(cycle.begin(), std::min_element(cycle.begin(), cycle.end()), cycle.end());
  cycle.push_back(cycle.front());
  return cycle;
}
bool contains(const Cycle& cycle, const DirectedEdge& edge) {
  for (std::size_t i = 1; i < cycle.size(); ++i)
    if (cycle[i-1] == edge.source && cycle[i] == edge.destination) return true;
  return false;
}
}

CandidateCycles::CandidateCycles(const PaperLayerwiseBatchMaintainer& model)
    : full_mask_((ColorMask{1} << model.hop_bound()) - 1) {
  // At most one state lookup per closing edge, not a cycle enumeration.
  for (const auto& edge : model.graph().edges())
    put(model, {edge.destination, edge.source});
}

void CandidateCycles::remove(const DirectedEdge& key) {
  const auto found = representatives_.find(key);
  if (found == representatives_.end()) return;
  const auto reference = references_.find(found->second);
  if (--reference->second == 0) {
    const auto value = values_.find(found->second);
    ordered_.erase({value->second, value->first});
    values_.erase(value); references_.erase(reference);
  }
  representatives_.erase(found);
}

void CandidateCycles::put(const PaperLayerwiseBatchMaintainer& model,
                          const DirectedEdge& key) {
  if (!model.graph().has_edge(key.destination, key.source)) return;
  const auto state = model.states().find({key.source, key.destination, full_mask_});
  if (state == model.states().end()) return;
  Cycle cycle = state->second.path; cycle.push_back(key.source);
  cycle = canonical(std::move(cycle));
  double weight = 0;
  for (std::size_t i = 1; i < cycle.size(); ++i)
    weight += *model.graph().edge_weight(cycle[i-1], cycle[i]);
  if (!std::isfinite(weight)) throw std::runtime_error("nonfinite cycle weight");
  const auto previous = values_.find(cycle);
  if (previous != values_.end()) ordered_.erase({previous->second, cycle});
  values_[cycle] = weight; ordered_.insert({weight, cycle});
  ++references_[cycle]; representatives_[key] = std::move(cycle);
}

void CandidateCycles::update(const PaperLayerwiseBatchMaintainer& model,
                             const LayerwiseBatchApplication& event) {
  std::set<DirectedEdge> dirty(event.changed_closed_states.begin(),
                               event.changed_closed_states.end());
  // A closing edge can change even when its reverse full-color DP state does
  // not. Include insertions and deletions as well as reweights.
  for (const auto& edge : event.effective_updates)
    dirty.insert({edge.destination, edge.source});
  for (const auto& key : dirty) remove(key);
  for (const auto& key : dirty) put(model, key);
}

CycleAnswer CandidateCycles::best() const {
  if (ordered_.empty()) return {};
  return {true, ordered_.begin()->first, ordered_.begin()->second};
}
double CandidateCycles::gap() const {
  if (ordered_.empty()) return 0;
  if (ordered_.size() == 1) return std::numeric_limits<double>::infinity();
  auto next = ordered_.begin(); const double first = next++->first;
  return next->first - first;
}

PaperEdgeGrouping::PaperEdgeGrouping(DirectedWeightedGraph graph, ColorMap colors,
                                   std::uint32_t k, DependencyGraphMode mode)
    : model_(graph, colors, k), live_(std::move(graph)),
      candidates_(model_), mode_(mode),
      anchor_(candidates_.best()), gap_(candidates_.gap()) {}

GroupingEvent PaperEdgeGrouping::update(const EdgeUpdate& update) {
  if (model_.colors().count(update.source) == 0 || model_.colors().count(update.destination) == 0)
    throw std::invalid_argument("all vertex colors must be predeclared");
  if (!update.erase && !std::isfinite(update.weight)) throw std::invalid_argument("finite update required");
  const DirectedEdge edge{update.source, update.destination};
  const auto old = live_.edge_weight(edge.source, edge.destination);
  if ((update.erase && !old) || (!update.erase && old && *old == update.weight)) return {};
  const bool is_new = !old && !update.erase;
  const bool same_color = model_.colors().at(edge.source) == model_.colors().at(edge.destination);
  const bool on_best = anchor_.exists && contains(anchor_.cycle, edge);
  double adverse = 0;
  if (!same_color && old && !update.erase)
    adverse = on_best ? std::max(0.0, update.weight - *old) : std::max(0.0, *old - update.weight);
  if (update.erase && on_best) adverse = std::numeric_limits<double>::infinity();
  pending_.push_back(update);
  if (update.erase) live_.remove_edge(edge.source, edge.destination);
  else live_.set_edge(edge.source, edge.destination, update.weight);
  // New edges and deletion of the selected cycle force maintenance. The latter
  // avoids inf <= inf in the one-candidate case, an explicit completion rule.
  // A same-color edge belongs to no colorful path/cycle in this fixed
  // instance. Retain its graph update for the next batch, without consuming
  // the cycle gap or forcing maintenance (even if it is a new edge).
  const bool immediate = !same_color && (is_new || !anchor_.exists || (update.erase && on_best)
                      || accumulated_ + adverse > gap_);
  const double prior_gap = gap_;
  accumulated_ += adverse;
  if (immediate) {
    auto result = flush(); result.adverse_change = adverse; result.gap_before = prior_gap;
    return result;
  }
  GroupingEvent result; result.deferred = true;
  result.adverse_change = adverse; result.gap_before = prior_gap;
  return result;
}

GroupingEvent PaperEdgeGrouping::flush() {
  GroupingEvent result;
  if (pending_.empty()) return result;
  result.maintained = true; result.batch_size = pending_.size();
#ifdef TRADER_PROFILE
  using Clock = std::chrono::steady_clock;
  auto started = Clock::now();
#endif
#ifdef TRADER_PROFILE
  auto snapshot = Clock::now();
#endif
  result.layerwise = model_.apply_batch(pending_, mode_);
#ifdef TRADER_PROFILE
  auto dp = Clock::now();
#endif
  candidates_.update(model_, result.layerwise);
#ifdef TRADER_PROFILE
  auto candidate = Clock::now();
  result.snapshot_ms = std::chrono::duration<double,std::milli>(snapshot-started).count();
  result.dp_ms = std::chrono::duration<double,std::milli>(dp-snapshot).count();
  result.candidate_ms = std::chrono::duration<double,std::milli>(candidate-dp).count();
#endif
  anchor_ = candidates_.best(); gap_ = candidates_.gap(); accumulated_ = 0;
  pending_.clear();
  return result;
}

CycleAnswer PaperEdgeGrouping::answer() const {
  if (!anchor_.exists) return {};
  CycleAnswer result = anchor_; result.weight = 0;
  // Even a deferred update may change C1's current weight while preserving its
  // optimal identity. Do not return a stale stored weight to the evaluator.
  for (std::size_t i = 1; i < result.cycle.size(); ++i) {
    auto weight = live_.edge_weight(result.cycle[i-1], result.cycle[i]);
    if (!weight) throw std::runtime_error("selected cycle invalid after grouping");
    result.weight += *weight;
  }
  return result;
}
} // namespace trader::paper_batch
