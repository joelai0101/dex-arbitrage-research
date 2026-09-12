#pragma once
#include "paper_batch_layerwise_model.h"
#include <map>
#include <set>

namespace trader::paper_batch {
using Cycle = std::vector<VertexId>;

// One best full-color DP path per closing edge, deduplicated by cycle rotation.
// This compressed set preserves the two smallest distinct cycle weights; see
// the README proof. Keys change only at maintenance boundaries.
class CandidateCycles {
public:
  explicit CandidateCycles(const PaperLayerwiseBatchMaintainer&);
  void update(const PaperLayerwiseBatchMaintainer&, const LayerwiseBatchApplication&);
  CycleAnswer best() const;
  double gap() const;
  std::size_t size() const { return values_.size(); }
private:
  ColorMask full_mask_;
  std::map<DirectedEdge, Cycle> representatives_;
  std::map<Cycle, std::size_t> references_;
  std::map<Cycle, double> values_;
  std::set<std::pair<double, Cycle>> ordered_;
  void put(const PaperLayerwiseBatchMaintainer&, const DirectedEdge&);
  void remove(const DirectedEdge&);
};

struct GroupingEvent {
  bool maintained = false;
  bool deferred = false;
  double adverse_change = 0;
  double gap_before = 0;
  std::size_t batch_size = 0;
  LayerwiseBatchApplication layerwise;
#ifdef TRADER_PROFILE
  double snapshot_ms = 0;
  double dp_ms = 0;
  double candidate_ms = 0;
#endif
};

// Algorithm 4 reconstructed per coloring instance. live_ always reflects every
// arrival, while DP/candidate keys reflect the last maintenance boundary.
class PaperEdgeGrouping {
public:
  PaperEdgeGrouping(DirectedWeightedGraph, ColorMap, std::uint32_t,
                   DependencyGraphMode = DependencyGraphMode::UpdateEdgesOnly);
  GroupingEvent update(const EdgeUpdate&);
  GroupingEvent flush();
  CycleAnswer answer() const;
  const PaperLayerwiseBatchMaintainer& model() const { return model_; }
  const DirectedWeightedGraph& live_graph() const { return live_; }
  std::size_t candidates() const { return candidates_.size(); }
  double maintained_gap() const { return gap_; }
private:
  PaperLayerwiseBatchMaintainer model_;
  DirectedWeightedGraph live_;
  CandidateCycles candidates_;
  DependencyGraphMode mode_;
  std::vector<EdgeUpdate> pending_;
  CycleAnswer anchor_;
  double gap_ = 0;
  double accumulated_ = 0;
};
} // namespace trader::paper_batch
