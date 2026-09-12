#include "paper_batch_reference_model.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <map>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <vector>

namespace {

using trader::paper_batch::ColorMap;
using trader::paper_batch::CorrectnessFirstBatchMaintainer;
using trader::paper_batch::CycleAnswer;
using trader::paper_batch::Dag;
using trader::paper_batch::DependencyGraphMode;
using trader::paper_batch::DirectedEdge;
using trader::paper_batch::DirectedWeightedGraph;
using trader::paper_batch::EdgeUpdate;
using trader::paper_batch::Schedule;
using trader::paper_batch::SchedulePolicy;
using trader::paper_batch::StateTable;
using trader::paper_batch::TieBreakDirection;
using trader::paper_batch::VertexId;

int scenarios = 0;
int variant_runs = 0;

void require(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "BL-3 failure: " << message << '\n';
    std::abort();
  }
}

EdgeUpdate update(VertexId source, VertexId destination, double weight,
                  std::size_t arrival, bool erase = false) {
  return {
      source, destination, weight, erase, "event-" + std::to_string(arrival),
      arrival};
}

std::vector<SchedulePolicy> policies() {
  std::vector<SchedulePolicy> result;
  for (const TieBreakDirection vertex_ties :
       {TieBreakDirection::Ascending, TieBreakDirection::Descending}) {
    for (const TieBreakDirection edge_ties :
         {TieBreakDirection::Ascending, TieBreakDirection::Descending}) {
      for (const TieBreakDirection topological_ties :
           {TieBreakDirection::Ascending, TieBreakDirection::Descending}) {
        for (const bool reverse_dag_order : {false, true}) {
          result.push_back(
              {vertex_ties, edge_ties, topological_ties, reverse_dag_order});
        }
      }
    }
  }
  return result;
}

std::string schedule_fingerprint(const Schedule &schedule) {
  std::ostringstream output;
  for (const Dag &dag : schedule.dags) {
    output << '[';
    const auto forward = trader::paper_batch::forward_edge_order(
        dag, schedule.dependency_edges, schedule.policy.topological_ties);
    for (const std::size_t edge_index : forward) {
      const DirectedEdge &edge = schedule.dependency_edges.at(edge_index);
      output << edge.source << '>' << edge.destination << ',';
    }
    output << ']';
  }
  return output.str();
}

bool respects_order(const Dag &dag, const std::vector<DirectedEdge> &edges,
                    const std::vector<std::size_t> &order, bool forward) {
  std::map<std::size_t, std::size_t> position;
  for (std::size_t index = 0; index < order.size(); ++index) {
    position.emplace(order[index], index);
  }
  if (position.size() != dag.edge_indices.size()) {
    return false;
  }
  for (const std::size_t current_index : dag.edge_indices) {
    for (const std::size_t other_index : dag.edge_indices) {
      const DirectedEdge &current = edges.at(current_index);
      const DirectedEdge &other = edges.at(other_index);
      const bool dependency = forward ? other.destination == current.source
                                      : other.source == current.destination;
      if (dependency &&
          position.at(other_index) >= position.at(current_index)) {
        return false;
      }
    }
  }
  return true;
}

void require_legal_schedule(const Schedule &schedule,
                            const std::string &context) {
  require(trader::paper_batch::covers_every_edge_exactly_once(
              schedule.dags, schedule.dependency_edges.size()),
          context + ": DAGs do not cover each dependency edge once");
  for (const Dag &dag : schedule.dags) {
    require(trader::paper_batch::is_acyclic(dag, schedule.dependency_edges),
            context + ": cyclic DAG");
    const auto forward = trader::paper_batch::forward_edge_order(
        dag, schedule.dependency_edges, schedule.policy.topological_ties);
    const auto backward = trader::paper_batch::backward_edge_order(
        dag, schedule.dependency_edges, schedule.policy.topological_ties);
    require(respects_order(dag, schedule.dependency_edges, forward, true),
            context + ": illegal forward topological order");
    require(respects_order(dag, schedule.dependency_edges, backward, false),
            context + ": illegal backward topological order");
  }
}

void require_answer_equal(const CycleAnswer &expected,
                          const CycleAnswer &actual,
                          const std::string &context) {
  require(expected.exists == actual.exists,
          context + ": cycle existence changed with schedule");
  if (!expected.exists) {
    return;
  }
  require(std::abs(expected.weight - actual.weight) <= 1e-12,
          context + ": cycle weight changed with schedule");
  require(expected.cycle == actual.cycle,
          context + ": deterministic cycle witness changed with schedule");
}

void verify_scenario(const DirectedWeightedGraph &initial_graph,
                     const ColorMap &colors, std::uint32_t hop_bound,
                     const std::vector<EdgeUpdate> &updates,
                     const std::string &name) {
  ++scenarios;
  for (const DependencyGraphMode mode : {DependencyGraphMode::UpdateEdgesOnly,
                                         DependencyGraphMode::VertexInduced}) {
    StateTable reference_states;
    CycleAnswer reference_answer;
    bool have_reference = false;
    std::set<std::string> schedule_shapes;

    for (const SchedulePolicy &policy : policies()) {
      CorrectnessFirstBatchMaintainer candidate(initial_graph, colors,
                                                hop_bound);
      const auto application = candidate.apply_batch(updates, mode, policy);
      const std::string context =
          name + (mode == DependencyGraphMode::UpdateEdgesOnly
                      ? " update-edges"
                      : " vertex-induced");
      require_legal_schedule(application.schedule, context);
      schedule_shapes.insert(schedule_fingerprint(application.schedule));

      const StateTable oracle = trader::paper_batch::enumerate_state_oracle(
          candidate.graph(), candidate.colors(), candidate.hop_bound());
      const auto oracle_comparison =
          trader::paper_batch::compare_state_tables(oracle, candidate.states());
      require(oracle_comparison.equal, context + ": state oracle mismatch: " +
                                           oracle_comparison.first_difference);
      const CycleAnswer answer_oracle =
          trader::paper_batch::enumerate_cycle_oracle(
              candidate.graph(), candidate.colors(), candidate.hop_bound());
      require_answer_equal(answer_oracle, candidate.answer(),
                           context + " answer oracle");

      if (!have_reference) {
        reference_states = candidate.states();
        reference_answer = candidate.answer();
        have_reference = true;
      } else {
        const auto comparison = trader::paper_batch::compare_state_tables(
            reference_states, candidate.states());
        require(comparison.equal,
                context + ": complete state table depends on legal order: " +
                    comparison.first_difference);
        require_answer_equal(reference_answer, candidate.answer(), context);
      }
      ++variant_runs;
    }

    require(schedule_shapes.size() >= 2,
            name + ": policies did not exercise multiple legal schedules");
  }
}

void test_adversarial_multi_dag_ties() {
  DirectedWeightedGraph graph;
  for (VertexId vertex = 0; vertex < 8; ++vertex) {
    graph.add_vertex(vertex);
  }
  for (const auto &[source, destination, weight] :
       std::vector<std::tuple<VertexId, VertexId, double>>{{0, 1, 1.0},
                                                           {1, 2, 1.0},
                                                           {2, 0, 1.0},
                                                           {0, 3, 2.0},
                                                           {3, 2, 2.0},
                                                           {2, 4, 1.0},
                                                           {4, 5, 1.0},
                                                           {5, 2, 1.0},
                                                           {1, 6, 0.5},
                                                           {6, 7, 0.5},
                                                           {7, 1, 0.5},
                                                           {3, 6, 1.5}}) {
    graph.set_edge(source, destination, weight);
  }
  ColorMap colors;
  for (VertexId vertex = 0; vertex < 8; ++vertex) {
    colors[vertex] = vertex % 4;
  }
  const std::vector<EdgeUpdate> updates{
      update(0, 1, -2.0, 0), update(1, 2, -1.0, 1), update(2, 0, -3.0, 2),
      update(2, 4, -0.5, 3), update(4, 5, -0.5, 4), update(5, 2, -0.5, 5),
      update(1, 6, 3.0, 6),  update(6, 7, -2.0, 7), update(7, 1, -2.0, 8),
      update(3, 6, 0.0, 9)};
  verify_scenario(graph, colors, 4, updates, "adversarial multi-DAG");
}

void test_fixed_seed_generated_orders() {
  std::mt19937 generator(20260904U);
  std::uniform_real_distribution<double> weight(-4.0, 6.0);
  std::bernoulli_distribution edge_present(0.32);
  std::uniform_int_distribution<int> vertex(0, 7);

  for (int graph_index = 0; graph_index < 12; ++graph_index) {
    DirectedWeightedGraph graph;
    ColorMap colors;
    for (VertexId id = 0; id < 8; ++id) {
      graph.add_vertex(id);
      colors[id] = id % 4;
    }
    for (VertexId source = 0; source < 8; ++source) {
      for (VertexId destination = 0; destination < 8; ++destination) {
        if (source != destination && edge_present(generator)) {
          graph.set_edge(source, destination, weight(generator));
        }
      }
    }

    std::vector<EdgeUpdate> updates;
    for (std::size_t arrival = 0; arrival < 10; ++arrival) {
      VertexId source = static_cast<VertexId>(vertex(generator));
      VertexId destination = static_cast<VertexId>(vertex(generator));
      while (destination == source) {
        destination = static_cast<VertexId>(vertex(generator));
      }
      updates.push_back(update(source, destination, weight(generator), arrival,
                               arrival == 8));
    }
    verify_scenario(graph, colors, 4, updates,
                    "generated graph " + std::to_string(graph_index));
  }
}

} // namespace

int main() {
  test_adversarial_multi_dag_ties();
  test_fixed_seed_generated_orders();
  std::cout << "BL-3 passed: " << scenarios << " scenarios, " << variant_runs
            << " legal schedule runs, complete DP-state and answer-oracle "
               "equality.\n";
  return 0;
}
