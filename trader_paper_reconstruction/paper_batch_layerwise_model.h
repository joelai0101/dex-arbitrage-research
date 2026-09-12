#ifndef PAPER_BATCH_LAYERWISE_MODEL_H
#define PAPER_BATCH_LAYERWISE_MODEL_H

#include "paper_batch_reference_model.h"

#include <cstddef>
#include <set>
#include <vector>

namespace trader::paper_batch {

// Observable evidence for one Algorithm-3-style batch.  The two edge-order
// vectors are the effective coalesced updates actually visited by the forward
// and backward queues.  State counters describe the explicit completion of
// the paper's otherwise undefined apply(...).
struct LayerwiseBatchApplication {
  Schedule schedule;
  std::vector<DirectedEdge> effective_updates;
  std::vector<DirectedEdge> forward_applied_updates;
  std::vector<DirectedEdge> backward_applied_updates;
  std::size_t forward_candidate_seeds = 0;
  std::size_t backward_invalidation_seeds = 0;
  std::size_t queued_state_keys = 0;
  std::size_t processed_state_keys = 0;
  std::size_t changed_state_keys = 0;
  std::size_t removed_state_keys = 0;
  bool cross_dag_vertex_overlap = false;
  bool effective_update_coverage = false;
  bool every_state_processed_at_most_once = false;
#ifdef TRADER_PROFILE
  double setup_ms = 0;
  double seed_ms = 0;
  double propagation_ms = 0;
  std::size_t seed_prefixes_examined = 0;
  std::size_t proposal_attempts = 0;
  std::size_t repair_requests = 0;
  std::size_t repair_states = 0;
  std::size_t proposal_states = 0;
  std::size_t incoming_edges_scanned = 0;
  std::size_t incoming_state_lookups = 0;
#endif
};

// Paper-derived correctness completion of Algorithm 3.
//
// Directly reproduced from the paper:
//   1. last-write-wins update coalescing;
//   2. Algorithm 2 DAG decomposition;
//   3. forward topological and backward reverse-topological edge queues.
//
// Explicit completion for the paper's undefined apply(...):
//   1. apply the coalesced batch atomically to the graph;
//   2. forward apply seeds states that can use an updated edge;
//   3. backward apply seeds recurrence successors of increased/deleted edges;
//   4. recompute the union of affected states by increasing color-set size,
//      propagating a change only to the next DP layer.
//
// This class is intentionally separate from released KCycleColorCoding.  It
// reconstructs the paper's formal all-pairs DP semantics and must not be
// described as the authors' unpublished production implementation.
class PaperLayerwiseBatchMaintainer {
public:
  PaperLayerwiseBatchMaintainer(DirectedWeightedGraph graph, ColorMap colors,
                                std::uint32_t hop_bound);

  LayerwiseBatchApplication
  apply_batch(const std::vector<EdgeUpdate> &updates,
              DependencyGraphMode mode = DependencyGraphMode::UpdateEdgesOnly);

  LayerwiseBatchApplication apply_batch(const std::vector<EdgeUpdate> &updates,
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

#endif // PAPER_BATCH_LAYERWISE_MODEL_H
