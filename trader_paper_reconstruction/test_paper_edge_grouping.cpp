#include "paper_edge_grouping.h"
#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>

using namespace trader::paper_batch;
namespace {
std::size_t checks = 0;
void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
std::vector<double> all_cycle_weights(const DirectedWeightedGraph& graph,
                                      const ColorMap& colors, std::uint32_t k) {
  std::vector<double> weights;
  for (auto root : graph.vertices()) {
    std::vector<VertexId> path{root};
    std::function<void(ColorMask,double)> visit = [&](ColorMask mask, double weight) {
      if (path.size() == k) {
        const auto closing = graph.edge_weight(path.back(), root);
        if (closing) weights.push_back(weight + *closing);
        return;
      }
      for (const auto& [next,w] : graph.outgoing(path.back())) {
        const ColorMask bit = ColorMask{1} << colors.at(next);
        if (next <= root || (mask & bit)) continue;
        path.push_back(next); visit(mask | bit, weight+w); path.pop_back();
      }
    };
    visit(ColorMask{1} << colors.at(root), 0);
  }
  std::sort(weights.begin(),weights.end()); return weights;
}
void verify_top_two(const PaperLayerwiseBatchMaintainer& model,
                    const CycleAnswer& best, double gap) {
  const auto weights = all_cycle_weights(model.graph(),model.colors(),model.hop_bound());
  require(best.exists == !weights.empty(), "DP closure candidate existence mismatch");
  if (!weights.empty()) require(std::abs(best.weight-weights[0]) < 1e-9, "DP closure best mismatch");
  const double expected_gap = weights.empty() ? 0 : weights.size()==1
      ? std::numeric_limits<double>::infinity() : weights[1]-weights[0];
  require(gap == expected_gap || std::abs(gap-expected_gap) < 1e-9,
          "DP closure distinct runner-up gap mismatch");
  ++checks;
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
    verify_top_two(engine.model(),actual,engine.maintained_gap());
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
void same_color_updates_do_not_trigger() {
  for (const auto mode : {DependencyGraphMode::UpdateEdgesOnly, DependencyGraphMode::VertexInduced}) {
    DirectedWeightedGraph graph; ColorMap colors{{0,0},{1,1},{2,2},{3,1},{4,2}};
    graph.set_edge(0,1,-1); graph.set_edge(1,2,-1); graph.set_edge(2,0,-1);
    graph.set_edge(0,3,0); graph.set_edge(3,4,0); graph.set_edge(4,0,0);
    PaperEdgeGrouping engine(graph,colors,3,mode);
    auto event = engine.update({1,2,0,false,"pending colorful",1});
    require(event.deferred, "colorful change below gap must defer"); verify(engine,false);
    event = engine.update({1,3,-100,false,"same-color insertion",2});
    require(event.deferred && !event.maintained && event.adverse_change == 0,
            "same-color insertion must not trigger or consume cycle gap"); verify(engine,false);
    event = engine.update({1,3,-200,false,"same-color decrease",3});
    require(event.deferred && !event.maintained && event.adverse_change == 0,
            "same-color decrease must not consume cycle gap"); verify(engine,false);
    event = engine.update({1,3,0,true,"same-color deletion",4});
    require(event.deferred && !event.maintained, "same-color deletion must defer"); verify(engine,false);
    event = engine.update({1,2,3,false,"colorful trigger",5});
    require(event.maintained && event.batch_size == 5,
            "later maintenance must retain all deferred graph updates"); verify(engine,true);

    PaperEdgeGrouping empty(DirectedWeightedGraph{},colors,3,mode);
    event = empty.update({1,3,-100,false,"no-candidate same-color",1});
    require(event.deferred && !event.maintained, "no candidate does not make same-color edges relevant"); verify(empty,false);
    empty.flush(); verify(empty,true);
  }
}
void candidate_reweight_closure() {
  DirectedWeightedGraph graph; ColorMap colors{{0,0},{1,1},{2,2},{3,1},{4,2}};
  graph.set_edge(0,1,-1); graph.set_edge(1,2,-1); graph.set_edge(2,0,-1);
  graph.set_edge(0,3,0); graph.set_edge(3,4,0); graph.set_edge(4,0,0);
  PaperLayerwiseBatchMaintainer model(graph, colors, 3);
  CandidateCycles candidates(model);
  auto apply = [&](const EdgeUpdate& update) {
    const auto event = model.apply_batch({update});
    candidates.update(model,event);
    verify_top_two(model,candidates.best(),candidates.gap());
  };
  for (double weight : {-2.0, -2.0, 3.0, -3.0}) {
    graph.set_edge(0,1,weight);
    apply({0,1,weight,false,"reweight",1});
    require(candidates.size()==2, "reweight must retain distinct candidates");
    require(candidates.best().weight==enumerate_cycle_oracle(graph,colors,3).weight,
            "reweight ranking mismatch");
    ++checks;
  }
  graph.remove_edge(1,2);
  apply({1,2,0,true,"delete other edge",2});
  require(candidates.size()==1 && candidates.best().weight==0,
          "reweight must preserve incidence on other cycle edges"); ++checks;
  graph.set_edge(1,2,-1);
  apply({1,2,-1,false,"restore",3});
  require(candidates.size()==2 && candidates.best().weight==-5,
          "restored cycle must be rediscovered after reweight/delete"); ++checks;
}
void compressed_candidates_and_mixed_batches() {
  // K5 has 24 distinct directed Hamiltonian cycles, but only 20 closing edges.
  DirectedWeightedGraph graph; ColorMap colors;
  for (VertexId u=0;u<5;++u) {
    colors[u]=u;
    for (VertexId v=0;v<5;++v) if (u!=v) graph.set_edge(u,v,0);
  }
  PaperLayerwiseBatchMaintainer model(graph,colors,5);
  CandidateCycles candidates(model);
  require(all_cycle_weights(graph,colors,5).size()==24, "complete-5 cycle oracle count");
  require(candidates.size()<24 && candidates.gap()==0, "compression must retain distinct tied runner-up");
  verify_top_two(model,candidates.best(),candidates.gap());
  std::mt19937 rng(9132026);
  for (std::uint32_t k=2;k<=5;++k) for (int trial=0;trial<8;++trial) {
    DirectedWeightedGraph g; ColorMap c;
    const VertexId n=k+2;
    for (VertexId u=0;u<n;++u) {
      g.add_vertex(u); c[u]=u%k;
      for (VertexId v=0;v<n;++v) if (u!=v && rng()%3!=0)
        g.set_edge(u,v,(int(rng()%13)-6)/4.0);
    }
    PaperLayerwiseBatchMaintainer m(g,c,k); CandidateCycles index(m);
    verify_top_two(m,index.best(),index.gap());
    for (std::size_t row=1;row<=40;++row) {
      std::vector<EdgeUpdate> updates;
      for (int i=0;i<4;++i) {
        const VertexId u=rng()%n; VertexId v=rng()%n; if(u==v) v=(v+1)%n;
        updates.push_back({u,v,(int(rng()%17)-8)/4.0,rng()%4==0,"mixed",row});
      }
      const auto event=m.apply_batch(updates,trial%2 ? DependencyGraphMode::UpdateEdgesOnly : DependencyGraphMode::VertexInduced);
      index.update(m,event);
      verify_top_two(m,index.best(),index.gap());
      // Full reconstruction checks both newly exposed and removed representatives.
      CandidateCycles rebuilt(m);
      require(index.size()==rebuilt.size(), "incremental representative cardinality mismatch");
      require(index.best().exists==rebuilt.best().exists, "rebuilt representative existence mismatch");
      if(index.best().exists) require(index.best().weight==rebuilt.best().weight, "rebuilt representative weight mismatch");
    }
  }
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
  single_candidate(); same_color_updates_do_not_trigger(); candidate_reweight_closure();
  compressed_candidates_and_mixed_batches(); randomized();
  std::cout << "Algorithm 4 checks passed: " << checks << " answer/state checkpoints\n";
}
