#pragma once
#include "paper_batch_layerwise_model.h"
#include <map>
#include <set>

namespace trader::paper_batch {
using Cycle = std::vector<VertexId>;

// All distinct colorful exact-k cycles, canonicalized by rotation. Keys are
// updated only at maintenance boundaries. The second entry is a distinct C2.
class CandidateCycles {
public:
  CandidateCycles(const DirectedWeightedGraph&, const ColorMap&, std::uint32_t);
  void update(const DirectedWeightedGraph& before,
              const DirectedWeightedGraph& after,
              const std::vector<EdgeUpdate>& updates);
  CycleAnswer best() const;
  double gap() const;
  std::size_t size() const { return values_.size(); }
private:
  ColorMap colors_;
  std::uint32_t k_;
  std::map<Cycle, double> values_;
  std::set<std::pair<double, Cycle>> ordered_;
  std::map<DirectedEdge, std::set<Cycle>> incidence_;
  void discover(const DirectedWeightedGraph&, const DirectedEdge&);
  void extend(const DirectedWeightedGraph&, Cycle&, ColorMask);
  void put(const DirectedWeightedGraph&, Cycle);
  void remove(const Cycle&);
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
