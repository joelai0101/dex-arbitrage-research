#include "paper_edge_grouping.h"
#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <stdexcept>

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

CandidateCycles::CandidateCycles(const DirectedWeightedGraph& graph,
                                const ColorMap& colors, std::uint32_t k)
    : colors_(colors), k_(k) {
  if (k < 2 || k > 63) throw std::invalid_argument("k must be in [2,63]");
  for (auto vertex : graph.vertices())
    if (colors_.at(vertex) >= k_) throw std::invalid_argument("color out of range");
  // Explicit initialization cost: enumerate the maintained candidate universe.
  for (auto root : graph.vertices()) {
    Cycle path{root};
    extend(graph, path, ColorMask{1} << colors_.at(root));
  }
}

void CandidateCycles::extend(const DirectedWeightedGraph& graph, Cycle& path, ColorMask mask) {
  if (path.size() == k_) {
    if (graph.has_edge(path.back(), path.front())) {
      Cycle closed = path; closed.push_back(path.front()); put(graph, std::move(closed));
    }
    return;
  }
  for (const auto& [next, weight] : graph.outgoing(path.back())) {
    (void)weight;
    const auto color = colors_.at(next);
    if (color >= k_) throw std::invalid_argument("color out of range");
    const ColorMask bit = ColorMask{1} << color;
    if (mask & bit) continue;
    path.push_back(next); extend(graph, path, mask | bit); path.pop_back();
  }
}

void CandidateCycles::discover(const DirectedWeightedGraph& graph, const DirectedEdge& edge) {
  if (!graph.has_edge(edge.source, edge.destination)) return;
  const auto a = colors_.at(edge.source), b = colors_.at(edge.destination);
  if (a == b) return;
  Cycle path{edge.source, edge.destination};
  extend(graph, path, (ColorMask{1} << a) | (ColorMask{1} << b));
}

void CandidateCycles::remove(const Cycle& cycle) {
  auto found = values_.find(cycle);
  if (found == values_.end()) return;
  ordered_.erase({found->second, cycle}); values_.erase(found);
  for (std::size_t i = 1; i < cycle.size(); ++i) {
    const DirectedEdge edge{cycle[i-1], cycle[i]};
    auto bucket = incidence_.find(edge);
    bucket->second.erase(cycle);
    if (bucket->second.empty()) incidence_.erase(bucket);
  }
}

void CandidateCycles::put(const DirectedWeightedGraph& graph, Cycle cycle) {
  cycle = canonical(std::move(cycle));
  remove(cycle);
  double weight = 0;
  for (std::size_t i = 1; i < cycle.size(); ++i) {
    auto w = graph.edge_weight(cycle[i-1], cycle[i]);
    if (!w) return;
    weight += *w;
  }
  if (!std::isfinite(weight)) throw std::runtime_error("nonfinite cycle weight");
  values_[cycle] = weight; ordered_.insert({weight, cycle});
  for (std::size_t i = 1; i < cycle.size(); ++i)
    incidence_[{cycle[i-1], cycle[i]}].insert(cycle);
}

void CandidateCycles::update(const DirectedWeightedGraph& before,
                             const DirectedWeightedGraph& after,
                             const std::vector<EdgeUpdate>& updates) {
  std::set<DirectedEdge> touched;
  for (const auto& update : updates) touched.insert({update.source, update.destination});
  std::set<Cycle> dirty;
  for (const auto& edge : touched) {
    auto found = incidence_.find(edge);
    if (found != incidence_.end()) dirty.insert(found->second.begin(), found->second.end());
  }
  for (const auto& cycle : dirty) put(after, cycle);
  for (const auto& edge : touched)
    if (!before.has_edge(edge.source, edge.destination) && after.has_edge(edge.source, edge.destination))
      discover(after, edge);
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
      candidates_(live_, colors, k), mode_(mode),
      anchor_(candidates_.best()), gap_(candidates_.gap()) {}

GroupingEvent PaperEdgeGrouping::update(const EdgeUpdate& update) {
  if (model_.colors().count(update.source) == 0 || model_.colors().count(update.destination) == 0)
    throw std::invalid_argument("all vertex colors must be predeclared");
  if (!update.erase && !std::isfinite(update.weight)) throw std::invalid_argument("finite update required");
  const DirectedEdge edge{update.source, update.destination};
  const auto old = live_.edge_weight(edge.source, edge.destination);
  if ((update.erase && !old) || (!update.erase && old && *old == update.weight)) return {};
  const bool is_new = !old && !update.erase;
  const bool on_best = anchor_.exists && contains(anchor_.cycle, edge);
  double adverse = 0;
  if (old && !update.erase)
    adverse = on_best ? std::max(0.0, update.weight - *old) : std::max(0.0, *old - update.weight);
  if (update.erase && on_best) adverse = std::numeric_limits<double>::infinity();
  pending_.push_back(update);
  if (update.erase) live_.remove_edge(edge.source, edge.destination);
  else live_.set_edge(edge.source, edge.destination, update.weight);
  // New edges and deletion of the selected cycle force maintenance. The latter
  // avoids inf <= inf in the one-candidate case, an explicit completion rule.
  const bool immediate = is_new || !anchor_.exists || (update.erase && on_best)
                      || accumulated_ + adverse > gap_;
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
  const auto before = model_.graph();
  result.layerwise = model_.apply_batch(pending_, mode_);
  candidates_.update(before, model_.graph(), pending_);
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
