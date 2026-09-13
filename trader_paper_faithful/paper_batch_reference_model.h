#ifndef PAPER_BATCH_REFERENCE_MODEL_H
#define PAPER_BATCH_REFERENCE_MODEL_H

#include "paper_batch_scheduler.h"

#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace trader::paper_batch {

using Color = std::uint32_t;
using ColorMask = std::uint64_t;
using ColorMap = std::map<VertexId, Color>;

class DirectedWeightedGraph {
public:
  void add_vertex(VertexId vertex);
  void set_edge(VertexId source, VertexId destination, double weight);
  void remove_edge(VertexId source, VertexId destination);

  bool has_edge(VertexId source, VertexId destination) const;
  std::optional<double> edge_weight(VertexId source,
                                    VertexId destination) const;
  const std::map<VertexId, double> &outgoing(VertexId source) const;
  const std::map<VertexId, double> &incoming(VertexId destination) const;
  const std::set<VertexId> &vertices() const;
  std::vector<DirectedEdge> edges() const;

private:
  std::set<VertexId> vertices_;
  std::map<VertexId, std::map<VertexId, double>> outgoing_;
  std::map<VertexId, std::map<VertexId, double>> incoming_;
};

struct StateKey {
  VertexId source = 0;
  VertexId destination = 0;
  ColorMask colors = 0;

  bool operator<(const StateKey &other) const {
    if (destination != other.destination) {
      return destination < other.destination;
    }
    if (source != other.source) {
      return source < other.source;
    }
    return colors < other.colors;
  }
};

struct StateValue {
  double weight = 0.0;
  std::vector<VertexId> path;
};

using StateTable = std::map<StateKey, StateValue>;

struct CycleAnswer {
  bool exists = false;
  double weight = 0.0;
  std::vector<VertexId> cycle;
};

struct StateComparison {
  bool equal = false;
  std::size_t expected_states = 0;
  std::size_t actual_states = 0;
  std::size_t missing_states = 0;
  std::size_t unexpected_states = 0;
  std::size_t weight_mismatches = 0;
  std::string first_difference;
};

struct BatchApplication {
  Schedule schedule;
  std::set<VertexId> rebuilt_sources;
  bool cross_dag_vertex_overlap = false;
};

// Production-side correctness model: color-subset dynamic programming. This
// deliberately differs from the exhaustive DFS oracle below.
StateTable build_static_dp(const DirectedWeightedGraph &graph,
                           const ColorMap &colors, std::uint32_t hop_bound);

// Independent BL-2 state oracle: enumerate every simple colorful path.
StateTable enumerate_state_oracle(const DirectedWeightedGraph &graph,
                                  const ColorMap &colors,
                                  std::uint32_t hop_bound);

CycleAnswer answer_from_dp(const DirectedWeightedGraph &graph,
                           const StateTable &states, std::uint32_t hop_bound);

// Independent BL-2 answer oracle: enumerate every colorful k-cycle directly.
CycleAnswer enumerate_cycle_oracle(const DirectedWeightedGraph &graph,
                                   const ColorMap &colors,
                                   std::uint32_t hop_bound);

StateComparison compare_state_tables(const StateTable &expected,
                                     const StateTable &actual,
                                     double absolute_tolerance = 1e-12);

bool is_legal_colorful_cycle(const DirectedWeightedGraph &graph,
                             const ColorMap &colors, std::uint32_t hop_bound,
                             const std::vector<VertexId> &cycle,
                             double expected_weight,
                             double absolute_tolerance = 1e-12);

// Correctness-first completion of the paper's undefined apply(...):
// 1. coalesce updates with last-write-wins;
// 2. build the selected paper-derived schedule for observability;
// 3. apply the coalesced updates atomically to obtain the batch-final graph;
// 4. conservatively identify source rows that can reach an updated edge's
//    source in the old or final graph within k-1 edges;
// 5. rebuild those source rows using exact color-subset DP.
//
// This resolves increase/delete invalidation and cross-DAG ordering for BL-2.
// It is an explicit reconstruction contract, not a claim about unpublished
// TRADER internals and not yet a performance optimization.
class CorrectnessFirstBatchMaintainer {
public:
  CorrectnessFirstBatchMaintainer(DirectedWeightedGraph graph, ColorMap colors,
                                  std::uint32_t hop_bound);

  BatchApplication apply_batch(const std::vector<EdgeUpdate> &updates,
                               DependencyGraphMode mode);

  BatchApplication apply_batch(const std::vector<EdgeUpdate> &updates,
                               DependencyGraphMode mode,
                               const SchedulePolicy &policy);

  const DirectedWeightedGraph &graph() const;
  const StateTable &states() const;
  const ColorMap &colors() const;
  std::uint32_t hop_bound() const;
  CycleAnswer answer() const;

private:
  DirectedWeightedGraph graph_;
  ColorMap colors_;
  std::uint32_t hop_bound_ = 0;
  StateTable states_;
};

} // namespace trader::paper_batch

#endif // PAPER_BATCH_REFERENCE_MODEL_H
