#include "paper_batch_reference_model.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <tuple>

namespace trader::paper_batch {
namespace {

const std::map<VertexId, double> kEmptyNeighbors;

std::size_t popcount(ColorMask mask) {
  std::size_t count = 0;
  while (mask != 0) {
    count += static_cast<std::size_t>(mask & 1U);
    mask >>= 1U;
  }
  return count;
}

ColorMask color_bit(Color color, std::uint32_t hop_bound) {
  if (color >= hop_bound || hop_bound == 0 || hop_bound > 63) {
    throw std::invalid_argument(
        "colors must be in [0, hop_bound), with hop_bound <= 63");
  }
  return ColorMask{1} << color;
}

void validate_graph_colors(const DirectedWeightedGraph &graph,
                           const ColorMap &colors, std::uint32_t hop_bound) {
  if (hop_bound < 2 || hop_bound > 63) {
    throw std::invalid_argument("hop_bound must be between 2 and 63");
  }
  for (const VertexId vertex : graph.vertices()) {
    const auto found = colors.find(vertex);
    if (found == colors.end()) {
      throw std::invalid_argument("fixed color map does not cover graph");
    }
    (void)color_bit(found->second, hop_bound);
  }
}

bool better_state(double candidate_weight,
                  const std::vector<VertexId> &candidate_path,
                  const StateValue &current) {
  if (candidate_weight < current.weight) {
    return true;
  }
  return candidate_weight == current.weight && candidate_path < current.path;
}

void insert_state(StateTable &states, const StateKey &key, double weight,
                  const std::vector<VertexId> &path) {
  const auto found = states.find(key);
  if (found == states.end()) {
    states.emplace(key, StateValue{weight, path});
    return;
  }
  if (better_state(weight, path, found->second)) {
    found->second = StateValue{weight, path};
  }
}

StateTable build_dp_for_sources(const DirectedWeightedGraph &graph,
                                const ColorMap &colors, std::uint32_t hop_bound,
                                const std::set<VertexId> &sources) {
  validate_graph_colors(graph, colors, hop_bound);
  StateTable states;
  for (const VertexId source : sources) {
    if (graph.vertices().count(source) == 0) {
      continue;
    }
    StateTable source_states;
    const ColorMask initial_mask = color_bit(colors.at(source), hop_bound);
    insert_state(source_states, {source, source, initial_mask}, 0.0, {source});

    for (std::size_t vertex_count = 1; vertex_count < hop_bound;
         ++vertex_count) {
      std::vector<std::pair<StateKey, StateValue>> layer;
      for (const auto &[key, value] : source_states) {
        if (popcount(key.colors) == vertex_count) {
          layer.emplace_back(key, value);
        }
      }

      for (const auto &[key, value] : layer) {
        for (const auto &[next, edge_weight] :
             graph.outgoing(key.destination)) {
          const ColorMask bit = color_bit(colors.at(next), hop_bound);
          if ((key.colors & bit) != 0) {
            continue;
          }
          std::vector<VertexId> path = value.path;
          path.push_back(next);
          insert_state(source_states, {source, next, key.colors | bit},
                       value.weight + edge_weight, path);
        }
      }
    }
    states.insert(source_states.begin(), source_states.end());
  }
  return states;
}

void enumerate_paths(const DirectedWeightedGraph &graph, const ColorMap &colors,
                     std::uint32_t hop_bound, VertexId source, VertexId current,
                     ColorMask mask, double weight, std::vector<VertexId> &path,
                     StateTable &states) {
  // Keep the exhaustive oracle's minimization independent from the
  // layer-by-layer DP helper above so a defect in insert_state/better_state
  // cannot make both implementations agree for the same wrong reason.
  const StateKey key{source, current, mask};
  const auto found = states.find(key);
  if (found == states.end()) {
    states.emplace(key, StateValue{weight, path});
  } else if (weight < found->second.weight ||
             (weight == found->second.weight && path < found->second.path)) {
    found->second.weight = weight;
    found->second.path = path;
  }
  if (path.size() >= hop_bound) {
    return;
  }

  for (const auto &[next, edge_weight] : graph.outgoing(current)) {
    const ColorMask bit = color_bit(colors.at(next), hop_bound);
    if ((mask & bit) != 0) {
      continue;
    }
    path.push_back(next);
    enumerate_paths(graph, colors, hop_bound, source, next, mask | bit,
                    weight + edge_weight, path, states);
    path.pop_back();
  }
}

std::vector<VertexId>
canonical_cycle(const std::vector<VertexId> &closed_cycle) {
  if (closed_cycle.size() < 2 || closed_cycle.front() != closed_cycle.back()) {
    throw std::invalid_argument("cycle must be closed");
  }
  std::vector<VertexId> open(closed_cycle.begin(), closed_cycle.end() - 1);
  std::vector<VertexId> best;
  for (std::size_t shift = 0; shift < open.size(); ++shift) {
    std::vector<VertexId> candidate;
    candidate.reserve(open.size() + 1);
    for (std::size_t offset = 0; offset < open.size(); ++offset) {
      candidate.push_back(open[(shift + offset) % open.size()]);
    }
    candidate.push_back(candidate.front());
    if (best.empty() || candidate < best) {
      best = std::move(candidate);
    }
  }
  return best;
}

void consider_cycle(double weight, const std::vector<VertexId> &cycle,
                    CycleAnswer &answer) {
  const std::vector<VertexId> canonical = canonical_cycle(cycle);
  if (!answer.exists || weight < answer.weight ||
      (weight == answer.weight && canonical < answer.cycle)) {
    answer.exists = true;
    answer.weight = weight;
    answer.cycle = canonical;
  }
}

void enumerate_cycles_from(const DirectedWeightedGraph &graph,
                           const ColorMap &colors, std::uint32_t hop_bound,
                           VertexId source, VertexId current, ColorMask mask,
                           double path_weight, std::vector<VertexId> &path,
                           CycleAnswer &answer) {
  if (path.size() == hop_bound) {
    const auto closing_weight = graph.edge_weight(current, source);
    if (closing_weight.has_value()) {
      std::vector<VertexId> cycle = path;
      cycle.push_back(source);
      consider_cycle(path_weight + *closing_weight, cycle, answer);
    }
    return;
  }

  for (const auto &[next, edge_weight] : graph.outgoing(current)) {
    const ColorMask bit = color_bit(colors.at(next), hop_bound);
    if ((mask & bit) != 0) {
      continue;
    }
    path.push_back(next);
    enumerate_cycles_from(graph, colors, hop_bound, source, next, mask | bit,
                          path_weight + edge_weight, path, answer);
    path.pop_back();
  }
}

std::set<VertexId> reverse_reachable_sources(const DirectedWeightedGraph &graph,
                                             VertexId target,
                                             std::uint32_t maximum_edges) {
  std::map<VertexId, std::vector<VertexId>> incoming;
  for (const DirectedEdge &edge : graph.edges()) {
    incoming[edge.destination].push_back(edge.source);
  }

  std::set<VertexId> reached;
  std::queue<std::pair<VertexId, std::uint32_t>> pending;
  reached.insert(target);
  pending.push({target, 0});
  while (!pending.empty()) {
    const auto [current, depth] = pending.front();
    pending.pop();
    if (depth == maximum_edges) {
      continue;
    }
    for (const VertexId predecessor : incoming[current]) {
      if (reached.insert(predecessor).second) {
        pending.push({predecessor, depth + 1});
      }
    }
  }
  return reached;
}

void erase_source_rows(StateTable &states, const std::set<VertexId> &sources) {
  for (auto iterator = states.begin(); iterator != states.end();) {
    if (sources.count(iterator->first.source) != 0) {
      iterator = states.erase(iterator);
    } else {
      ++iterator;
    }
  }
}

std::string state_text(const StateKey &key, const StateValue *value) {
  std::ostringstream stream;
  stream << '(' << key.source << ',' << key.destination
         << ",mask=" << key.colors << ')';
  if (value != nullptr) {
    stream << " weight=" << value->weight;
  }
  return stream.str();
}

} // namespace

void DirectedWeightedGraph::add_vertex(VertexId vertex) {
  vertices_.insert(vertex);
}

void DirectedWeightedGraph::set_edge(VertexId source, VertexId destination,
                                     double weight) {
  if (source == destination) {
    throw std::invalid_argument("self-loop edges are outside kMNC scope");
  }
  if (!std::isfinite(weight)) {
    throw std::invalid_argument(
        "finite edge write required; use remove_edge for deletion");
  }
  vertices_.insert(source);
  vertices_.insert(destination);
  outgoing_[source][destination] = weight;
  incoming_[destination][source] = weight;
}

void DirectedWeightedGraph::remove_edge(VertexId source, VertexId destination) {
  const auto found = outgoing_.find(source);
  if (found == outgoing_.end()) {
    return;
  }
  found->second.erase(destination);
  if (found->second.empty()) {
    outgoing_.erase(found);
  }
  const auto incoming_found = incoming_.find(destination);
  if (incoming_found != incoming_.end()) {
    incoming_found->second.erase(source);
    if (incoming_found->second.empty()) {
      incoming_.erase(incoming_found);
    }
  }
}

bool DirectedWeightedGraph::has_edge(VertexId source,
                                     VertexId destination) const {
  return edge_weight(source, destination).has_value();
}

std::optional<double>
DirectedWeightedGraph::edge_weight(VertexId source,
                                   VertexId destination) const {
  const auto source_found = outgoing_.find(source);
  if (source_found == outgoing_.end()) {
    return std::nullopt;
  }
  const auto destination_found = source_found->second.find(destination);
  if (destination_found == source_found->second.end()) {
    return std::nullopt;
  }
  return destination_found->second;
}

const std::map<VertexId, double> &
DirectedWeightedGraph::outgoing(VertexId source) const {
  const auto found = outgoing_.find(source);
  return found == outgoing_.end() ? kEmptyNeighbors : found->second;
}

const std::map<VertexId, double> &
DirectedWeightedGraph::incoming(VertexId destination) const {
  const auto found = incoming_.find(destination);
  return found == incoming_.end() ? kEmptyNeighbors : found->second;
}

const std::set<VertexId> &DirectedWeightedGraph::vertices() const {
  return vertices_;
}

std::vector<DirectedEdge> DirectedWeightedGraph::edges() const {
  std::vector<DirectedEdge> result;
  for (const auto &[source, destinations] : outgoing_) {
    for (const auto &[destination, ignored] : destinations) {
      (void)ignored;
      result.push_back({source, destination});
    }
  }
  return result;
}

StateTable build_static_dp(const DirectedWeightedGraph &graph,
                           const ColorMap &colors, std::uint32_t hop_bound) {
  return build_dp_for_sources(graph, colors, hop_bound, graph.vertices());
}

StateTable enumerate_state_oracle(const DirectedWeightedGraph &graph,
                                  const ColorMap &colors,
                                  std::uint32_t hop_bound) {
  validate_graph_colors(graph, colors, hop_bound);
  StateTable states;
  for (const VertexId source : graph.vertices()) {
    const ColorMask mask = color_bit(colors.at(source), hop_bound);
    std::vector<VertexId> path{source};
    enumerate_paths(graph, colors, hop_bound, source, source, mask, 0.0, path,
                    states);
  }
  return states;
}

CycleAnswer answer_from_dp(const DirectedWeightedGraph &graph,
                           const StateTable &states, std::uint32_t hop_bound) {
  if (hop_bound == 0 || hop_bound > 63) {
    throw std::invalid_argument("invalid hop bound");
  }
  const ColorMask full_mask = (ColorMask{1} << hop_bound) - ColorMask{1};
  CycleAnswer answer;
  for (const auto &[key, value] : states) {
    if (key.colors != full_mask || value.path.size() != hop_bound) {
      continue;
    }
    const auto closing_weight = graph.edge_weight(key.destination, key.source);
    if (!closing_weight.has_value()) {
      continue;
    }
    std::vector<VertexId> cycle = value.path;
    cycle.push_back(key.source);
    consider_cycle(value.weight + *closing_weight, cycle, answer);
  }
  return answer;
}

CycleAnswer enumerate_cycle_oracle(const DirectedWeightedGraph &graph,
                                   const ColorMap &colors,
                                   std::uint32_t hop_bound) {
  validate_graph_colors(graph, colors, hop_bound);
  CycleAnswer answer;
  for (const VertexId source : graph.vertices()) {
    const ColorMask mask = color_bit(colors.at(source), hop_bound);
    std::vector<VertexId> path{source};
    enumerate_cycles_from(graph, colors, hop_bound, source, source, mask, 0.0,
                          path, answer);
  }
  return answer;
}

StateComparison compare_state_tables(const StateTable &expected,
                                     const StateTable &actual,
                                     double absolute_tolerance) {
  StateComparison result;
  result.expected_states = expected.size();
  result.actual_states = actual.size();

  for (const auto &[key, expected_value] : expected) {
    const auto found = actual.find(key);
    if (found == actual.end()) {
      ++result.missing_states;
      if (result.first_difference.empty()) {
        result.first_difference = "missing " + state_text(key, &expected_value);
      }
      continue;
    }
    if (std::abs(expected_value.weight - found->second.weight) >
        absolute_tolerance) {
      ++result.weight_mismatches;
      if (result.first_difference.empty()) {
        result.first_difference = "weight mismatch expected " +
                                  state_text(key, &expected_value) +
                                  " actual " + state_text(key, &found->second);
      }
    }
  }
  for (const auto &[key, value] : actual) {
    if (expected.find(key) == expected.end()) {
      ++result.unexpected_states;
      if (result.first_difference.empty()) {
        result.first_difference = "unexpected " + state_text(key, &value);
      }
    }
  }
  result.equal = result.missing_states == 0 && result.unexpected_states == 0 &&
                 result.weight_mismatches == 0;
  return result;
}

bool is_legal_colorful_cycle(const DirectedWeightedGraph &graph,
                             const ColorMap &colors, std::uint32_t hop_bound,
                             const std::vector<VertexId> &cycle,
                             double expected_weight,
                             double absolute_tolerance) {
  if (cycle.size() != hop_bound + 1 || cycle.front() != cycle.back()) {
    return false;
  }
  std::set<VertexId> unique_vertices;
  ColorMask mask = 0;
  double weight = 0.0;
  for (std::size_t index = 0; index < hop_bound; ++index) {
    const VertexId vertex = cycle[index];
    if (!unique_vertices.insert(vertex).second) {
      return false;
    }
    const auto color = colors.find(vertex);
    if (color == colors.end()) {
      return false;
    }
    const ColorMask bit = color_bit(color->second, hop_bound);
    if ((mask & bit) != 0) {
      return false;
    }
    mask |= bit;
    const auto edge = graph.edge_weight(vertex, cycle[index + 1]);
    if (!edge.has_value()) {
      return false;
    }
    weight += *edge;
  }
  const ColorMask full_mask = (ColorMask{1} << hop_bound) - ColorMask{1};
  return mask == full_mask &&
         std::abs(weight - expected_weight) <= absolute_tolerance;
}

CorrectnessFirstBatchMaintainer::CorrectnessFirstBatchMaintainer(
    DirectedWeightedGraph graph, ColorMap colors, std::uint32_t hop_bound)
    : graph_(std::move(graph)), colors_(std::move(colors)),
      hop_bound_(hop_bound) {
  validate_graph_colors(graph_, colors_, hop_bound_);
  states_ = build_static_dp(graph_, colors_, hop_bound_);
}

BatchApplication CorrectnessFirstBatchMaintainer::apply_batch(
    const std::vector<EdgeUpdate> &updates, DependencyGraphMode mode) {
  return apply_batch(updates, mode, SchedulePolicy{});
}

BatchApplication CorrectnessFirstBatchMaintainer::apply_batch(
    const std::vector<EdgeUpdate> &updates, DependencyGraphMode mode,
    const SchedulePolicy &policy) {
  BatchApplication result;
  const DirectedWeightedGraph old_graph = graph_;
  result.schedule = build_schedule(updates, old_graph.edges(), mode, policy);
  result.cross_dag_vertex_overlap =
      has_cross_dag_vertex_overlap(result.schedule.dags);

  for (const EdgeUpdate &update : result.schedule.coalesced_updates) {
    if (update.erase) {
      // A deletion of an edge/endpoint absent from the current graph is a
      // semantic no-op and therefore does not require a color assignment.
      graph_.remove_edge(update.source, update.destination);
    } else {
      if (colors_.find(update.source) == colors_.end() ||
          colors_.find(update.destination) == colors_.end()) {
        throw std::invalid_argument(
            "fixed color map must cover every finite update endpoint");
      }
      graph_.set_edge(update.source, update.destination, update.weight);
    }
  }
  validate_graph_colors(graph_, colors_, hop_bound_);

  for (const EdgeUpdate &update : result.schedule.coalesced_updates) {
    const auto old_sources =
        reverse_reachable_sources(old_graph, update.source, hop_bound_ - 1);
    const auto new_sources =
        reverse_reachable_sources(graph_, update.source, hop_bound_ - 1);
    result.rebuilt_sources.insert(old_sources.begin(), old_sources.end());
    result.rebuilt_sources.insert(new_sources.begin(), new_sources.end());
    // Endpoints are included so newly inserted isolated vertices receive
    // their zero-hop source state and deleted endpoints remain represented.
    result.rebuilt_sources.insert(update.source);
    result.rebuilt_sources.insert(update.destination);
  }

  erase_source_rows(states_, result.rebuilt_sources);
  const StateTable rebuilt =
      build_dp_for_sources(graph_, colors_, hop_bound_, result.rebuilt_sources);
  states_.insert(rebuilt.begin(), rebuilt.end());
  return result;
}

const DirectedWeightedGraph &CorrectnessFirstBatchMaintainer::graph() const {
  return graph_;
}

const StateTable &CorrectnessFirstBatchMaintainer::states() const {
  return states_;
}

const ColorMap &CorrectnessFirstBatchMaintainer::colors() const {
  return colors_;
}

std::uint32_t CorrectnessFirstBatchMaintainer::hop_bound() const {
  return hop_bound_;
}

CycleAnswer CorrectnessFirstBatchMaintainer::answer() const {
  return answer_from_dp(graph_, states_, hop_bound_);
}

} // namespace trader::paper_batch
