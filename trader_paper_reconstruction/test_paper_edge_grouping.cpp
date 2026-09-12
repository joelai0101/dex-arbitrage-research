#include "paper_edge_grouping.h"
#include <cmath>
#include <iostream>
#include <random>
#include <stdexcept>

using namespace trader::paper_batch;
namespace {
std::size_t checks = 0;
void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
void verify(const PaperEdgeGrouping& engine, bool maintained) {
  const auto expected = enumerate_cycle_oracle(engine.live_graph(), engine.model().colors(), engine.model().hop_bound());
  const auto actual = engine.answer();
  require(actual.exists == expected.exists, "cycle existence mismatch");
  if (actual.exists) {
    require(std::abs(actual.weight - expected.weight) < 1e-9, "global colorful optimum mismatch");
    require(is_legal_colorful_cycle(engine.live_graph(), engine.model().colors(), engine.model().hop_bound(), actual.cycle, actual.weight, 1e-9), "illegal returned witness");
  }
  if (maintained) {
    const auto states = enumerate_state_oracle(engine.live_graph(), engine.model().colors(), engine.model().hop_bound());
    require(compare_state_tables(states, engine.model().states(), 1e-9).equal, "DP state mismatch after maintenance");
  }
  ++checks;
}
void boundaries(DependencyGraphMode mode) {
  DirectedWeightedGraph graph;
  ColorMap colors{{0,0},{1,1},{2,2},{3,1},{4,2}};
  graph.set_edge(0,1,-1); graph.set_edge(1,2,-1); graph.set_edge(2,0,-1);
  graph.set_edge(0,3,0); graph.set_edge(3,4,0); graph.set_edge(4,0,0);
  PaperEdgeGrouping engine(graph, colors, 3, mode);
  require(engine.candidates() == 2, "rotated cycles must not duplicate C2");
  auto event = engine.update({1,2,0,false,"1",1});
  require(event.deferred && !event.maintained && event.gap_before == 3, "below-gap update must defer"); verify(engine, false);
  event = engine.update({1,2,2,false,"2",2});
  require(event.deferred && engine.answer().weight == 0, "equal-gap tie may defer with current weight"); verify(engine, false);
  event = engine.update({1,2,3,false,"3",3});
  require(event.maintained && event.batch_size == 3, "cumulative gap must trigger coalesced batch"); verify(engine, true);
  event = engine.update({3,4,-0.5,false,"4",4});
  require(event.deferred && engine.answer().weight == -0.5, "deferred C1 price must not be stale"); verify(engine, false);
  event = engine.update({1,4,-10,false,"5",5});
  require(event.maintained, "new edge must immediately maintain"); verify(engine, true);
  event = engine.update({1,4,0,true,"6",6});
  require(event.maintained, "selected-cycle deletion must immediately maintain"); verify(engine, true);
  event = engine.update({0,3,0.25,false,"7",7}); verify(engine, event.maintained);
  engine.flush(); verify(engine, true);
}
void single_candidate() {
  DirectedWeightedGraph graph; ColorMap colors{{0,0},{1,1},{2,2}};
  graph.set_edge(0,1,-1); graph.set_edge(1,2,-1); graph.set_edge(2,0,-1);
  PaperEdgeGrouping engine(graph, colors, 3);
  auto event = engine.update({0,1,2,false,"1",1});
  require(event.deferred, "one candidate has infinite gap"); verify(engine, false);
  event = engine.update({0,1,0,true,"2",2});
  require(event.maintained, "infinite gap cannot defer selected deletion"); verify(engine, true);
}
void candidate_reweight_incidence() {
  DirectedWeightedGraph graph; ColorMap colors{{0,0},{1,1},{2,2},{3,1},{4,2}};
  graph.set_edge(0,1,-1); graph.set_edge(1,2,-1); graph.set_edge(2,0,-1);
  graph.set_edge(0,3,0); graph.set_edge(3,4,0); graph.set_edge(4,0,0);
  CandidateCycles candidates(graph, colors, 3);
  for (double weight : {-2.0, -2.0, 3.0, -3.0}) {
    auto before = graph; graph.set_edge(0,1,weight);
    candidates.update(before,graph,{{0,1,weight,false,"reweight",1}});
    require(candidates.size()==2, "reweight must retain distinct candidates");
    require(candidates.best().weight==enumerate_cycle_oracle(graph,colors,3).weight,
            "reweight ranking mismatch");
    ++checks;
  }
  auto before = graph; graph.remove_edge(1,2);
  candidates.update(before,graph,{{1,2,0,true,"delete other edge",2}});
  require(candidates.size()==1 && candidates.best().weight==0,
          "reweight must preserve incidence on other cycle edges"); ++checks;
  before = graph; graph.set_edge(1,2,-1);
  candidates.update(before,graph,{{1,2,-1,false,"restore",3}});
  require(candidates.size()==2 && candidates.best().weight==-5,
          "restored cycle must be rediscovered after reweight/delete"); ++checks;
}
void randomized() {
  std::mt19937 random(9122026);
  for (auto mode : {DependencyGraphMode::UpdateEdgesOnly, DependencyGraphMode::VertexInduced})
    for (int trial = 0; trial < 20; ++trial) {
      const std::uint32_t k = 3 + trial % 3, n = k + 2;
      DirectedWeightedGraph graph; ColorMap colors;
      for (std::uint32_t u = 0; u < n; ++u) { graph.add_vertex(u); colors[u] = u % k; }
      for (std::uint32_t u = 0; u < n; ++u)
        for (std::uint32_t v = 0; v < n; ++v)
          if (u != v && random()%4 == 0) graph.set_edge(u,v,(int(random()%17)-8)/4.0);
      PaperEdgeGrouping engine(graph, colors, k, mode); verify(engine, true);
      for (std::size_t row = 1; row <= 120; ++row) {
        const VertexId u = static_cast<VertexId>(random()%n);
        VertexId v = static_cast<VertexId>(random()%n); if (u == v) v = (v+1)%n;
        auto event = engine.update({u,v,(int(random()%25)-12)/4.0,random()%7==0,std::to_string(row),row});
        if (event.maintained) {
          require(event.layerwise.effective_update_coverage, "missing Algorithm 3 edge coverage");
          require(event.layerwise.every_state_processed_at_most_once, "duplicate DP work within pass");
        }
        verify(engine, event.maintained);
      }
      engine.flush(); verify(engine, true);
    }
}
}
int main() {
  boundaries(DependencyGraphMode::UpdateEdgesOnly);
  boundaries(DependencyGraphMode::VertexInduced);
  single_candidate(); candidate_reweight_incidence(); randomized();
  std::cout << "Algorithm 4 checks passed: " << checks << " answer/state checkpoints\n";
}
