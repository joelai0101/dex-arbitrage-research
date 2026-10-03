#ifndef PAPER_BATCH_SCHEDULER_H
#define PAPER_BATCH_SCHEDULER_H

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace trader::paper_batch {

using VertexId = std::uint32_t;

enum class DependencyGraphMode {
  // Algorithm 3 / Figure 7 reading: only coalesced update edges are
  // decomposed and ordered.
  UpdateEdgesOnly,
  // Definition V.1 reading: all existing edges between batch endpoint
  // vertices, plus the update edges themselves, form the dependency graph.
  VertexInduced,
};

enum class TieBreakDirection {
  Ascending,
  Descending,
};

// Algorithms 2 and 3 permit more than one legal choice when degrees or
// topological ranks tie. BL-3 varies these choices explicitly.
struct SchedulePolicy {
  TieBreakDirection vertex_ties = TieBreakDirection::Ascending;
  TieBreakDirection edge_ties = TieBreakDirection::Ascending;
  TieBreakDirection topological_ties = TieBreakDirection::Ascending;
  bool reverse_dag_order = false;
};

struct DirectedEdge {
  VertexId source = 0;
  VertexId destination = 0;

  bool operator==(const DirectedEdge &other) const {
    return source == other.source && destination == other.destination;
  }

  bool operator<(const DirectedEdge &other) const {
    if (source != other.source) {
      return source < other.source;
    }
    return destination < other.destination;
  }
};

struct EdgeUpdate {
  VertexId source = 0;
  VertexId destination = 0;
  double weight = 0.0;
  bool erase = false;
  std::string event_id;
  std::size_t arrival_index = 0;
};

struct Dag {
  std::vector<VertexId> vertices;
  // Indices into Schedule::dependency_edges (or the edge vector supplied to
  // decompose_into_dags).
  std::vector<std::size_t> edge_indices;
};

struct Schedule {
  DependencyGraphMode mode = DependencyGraphMode::UpdateEdgesOnly;
  SchedulePolicy policy;
  std::vector<EdgeUpdate> coalesced_updates;
  std::vector<DirectedEdge> dependency_edges;
  std::vector<Dag> dags;
};

// Algorithm 3, Step 1. The final update for each directed edge wins; output is
// ordered by the retained update's arrival index and then by edge key.
std::vector<EdgeUpdate> coalesce_latest(const std::vector<EdgeUpdate> &updates);

// Resolve the paper's two plausible dependency-graph readings explicitly.
std::vector<DirectedEdge>
build_dependency_edges(const std::vector<EdgeUpdate> &coalesced_updates,
                       const std::vector<DirectedEdge> &existing_edges,
                       DependencyGraphMode mode);

// Algorithm 2: deterministic greedy edge-disjoint DAG decomposition.
std::vector<Dag> decompose_into_dags(const std::vector<DirectedEdge> &edges);

std::vector<Dag> decompose_into_dags(const std::vector<DirectedEdge> &edges,
                                     const SchedulePolicy &policy);

// Algorithm 3, Step 3: deterministic dependency-edge orders induced by a
// DAG's topological vertex order.
std::vector<std::size_t>
forward_edge_order(const Dag &dag, const std::vector<DirectedEdge> &edges);

std::vector<std::size_t>
forward_edge_order(const Dag &dag, const std::vector<DirectedEdge> &edges,
                   TieBreakDirection topological_ties);

std::vector<std::size_t>
backward_edge_order(const Dag &dag, const std::vector<DirectedEdge> &edges);

std::vector<std::size_t>
backward_edge_order(const Dag &dag, const std::vector<DirectedEdge> &edges,
                    TieBreakDirection topological_ties);

Schedule build_schedule(const std::vector<EdgeUpdate> &updates,
                        const std::vector<DirectedEdge> &existing_edges,
                        DependencyGraphMode mode);

Schedule build_schedule(const std::vector<EdgeUpdate> &updates,
                        const std::vector<DirectedEdge> &existing_edges,
                        DependencyGraphMode mode, const SchedulePolicy &policy);

bool is_acyclic(const Dag &dag, const std::vector<DirectedEdge> &edges);

bool covers_every_edge_exactly_once(const std::vector<Dag> &dags,
                                    std::size_t edge_count);

bool respects_forward_dependencies(const Dag &dag,
                                   const std::vector<DirectedEdge> &edges);

bool respects_backward_dependencies(const Dag &dag,
                                    const std::vector<DirectedEdge> &edges);

bool has_cross_dag_vertex_overlap(const std::vector<Dag> &dags);

} // namespace trader::paper_batch

#endif // PAPER_BATCH_SCHEDULER_H
