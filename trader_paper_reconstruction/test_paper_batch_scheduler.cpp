#include "paper_batch_scheduler.h"

#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using trader::paper_batch::Dag;
using trader::paper_batch::DependencyGraphMode;
using trader::paper_batch::DirectedEdge;
using trader::paper_batch::EdgeUpdate;
using trader::paper_batch::Schedule;

int tests_run = 0;

void require(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "BL-1 failure: " << message << '\n';
    std::abort();
  }
}

EdgeUpdate update(std::uint32_t source, std::uint32_t destination,
                  double weight, std::size_t arrival, bool erase = false) {
  return {
      source, destination, weight, erase, "event-" + std::to_string(arrival),
      arrival};
}

std::string fingerprint(const Schedule &schedule) {
  std::ostringstream stream;
  stream << static_cast<int>(schedule.mode) << '|';
  for (const EdgeUpdate &item : schedule.coalesced_updates) {
    stream << item.source << '>' << item.destination << ':' << item.weight
           << ':' << item.erase << ':' << item.arrival_index << ';';
  }
  stream << '|';
  for (const DirectedEdge &edge : schedule.dependency_edges) {
    stream << edge.source << '>' << edge.destination << ';';
  }
  stream << '|';
  for (const Dag &dag : schedule.dags) {
    stream << '[';
    for (const auto vertex : dag.vertices) {
      stream << vertex << ',';
    }
    stream << ':';
    for (const auto index : dag.edge_indices) {
      stream << index << ',';
    }
    stream << ']';
  }
  return stream.str();
}

void validate_all_dags(const Schedule &schedule) {
  require(trader::paper_batch::covers_every_edge_exactly_once(
              schedule.dags, schedule.dependency_edges.size()),
          "dependency edges must be covered exactly once");
  for (const Dag &dag : schedule.dags) {
    require(trader::paper_batch::is_acyclic(dag, schedule.dependency_edges),
            "every decomposed component must be acyclic");
    require(trader::paper_batch::respects_forward_dependencies(
                dag, schedule.dependency_edges),
            "forward order must wait for every predecessor edge");
    require(trader::paper_batch::respects_backward_dependencies(
                dag, schedule.dependency_edges),
            "backward order must wait for every successor edge");
  }
}

void test_empty_batch() {
  ++tests_run;
  const Schedule result = trader::paper_batch::build_schedule(
      {}, {}, DependencyGraphMode::UpdateEdgesOnly);
  require(result.coalesced_updates.empty(), "empty batch coalescing");
  require(result.dependency_edges.empty(), "empty dependency graph");
  require(result.dags.empty(), "empty DAG list");
}

void test_coalescing_is_last_write_wins() {
  ++tests_run;
  const std::vector<EdgeUpdate> input = {
      update(1, 2, 10.0, 4),
      update(2, 3, 20.0, 2),
      update(1, 2, 30.0, 7, true),
      update(2, 3, 40.0, 5),
  };
  const auto output = trader::paper_batch::coalesce_latest(input);
  require(output.size() == 2, "one retained update per directed edge");
  require(output[0].source == 2 && output[0].destination == 3,
          "retained updates ordered by final arrival");
  require(output[0].weight == 40.0 && output[0].arrival_index == 5,
          "2->3 must keep its final value");
  require(output[1].source == 1 && output[1].destination == 2,
          "1->2 retained after later timestamp");
  require(output[1].erase && output[1].arrival_index == 7,
          "last deletion must supersede an earlier write");
}

void test_chain_orders_forward_and_backward() {
  ++tests_run;
  const std::vector<EdgeUpdate> updates = {
      update(3, 4, 1.0, 2),
      update(1, 2, 1.0, 0),
      update(2, 3, 1.0, 1),
  };
  const Schedule schedule = trader::paper_batch::build_schedule(
      updates, {}, DependencyGraphMode::UpdateEdgesOnly);
  validate_all_dags(schedule);
  // Algorithm 2 starts from the highest-total-degree vertex and follows only
  // outgoing edges. It may therefore split an acyclic chain at an internal
  // vertex. Test the layer order on the complete acyclic dependency graph,
  // while the generated schedule is checked separately for exact coverage.
  Dag complete_chain{{1, 2, 3, 4}, {0, 1, 2}};
  const auto forward = trader::paper_batch::forward_edge_order(
      complete_chain, schedule.dependency_edges);
  require(schedule.dependency_edges[forward[0]] == DirectedEdge{1, 2},
          "forward chain starts at source edge");
  require(schedule.dependency_edges[forward[2]] == DirectedEdge{3, 4},
          "forward chain ends at sink edge");
  const auto backward = trader::paper_batch::backward_edge_order(
      complete_chain, schedule.dependency_edges);
  require(schedule.dependency_edges[backward[0]] == DirectedEdge{3, 4},
          "backward chain starts at sink edge");
}

void test_multi_parent_and_multi_successor_dependencies() {
  ++tests_run;
  const std::vector<EdgeUpdate> updates = {
      update(1, 2, 1.0, 0), update(1, 3, 1.0, 1), update(2, 4, 1.0, 2),
      update(3, 4, 1.0, 3), update(4, 5, 1.0, 4), update(4, 6, 1.0, 5),
  };
  const Schedule schedule = trader::paper_batch::build_schedule(
      updates, {}, DependencyGraphMode::UpdateEdgesOnly);
  validate_all_dags(schedule);
  Dag complete_diamond{
      {1, 2, 3, 4, 5, 6},
      {0, 1, 2, 3, 4, 5},
  };
  require(trader::paper_batch::is_acyclic(complete_diamond,
                                          schedule.dependency_edges),
          "complete diamond dependency graph must be acyclic");
  require(trader::paper_batch::respects_forward_dependencies(
              complete_diamond, schedule.dependency_edges),
          "complete diamond must wait for all forward predecessors");
  require(trader::paper_batch::respects_backward_dependencies(
              complete_diamond, schedule.dependency_edges),
          "complete diamond must wait for all backward successors");
}

void test_directed_cycle_is_split_without_losing_edges() {
  ++tests_run;
  const std::vector<EdgeUpdate> updates = {
      update(1, 2, 1.0, 0),
      update(2, 3, 1.0, 1),
      update(3, 1, 1.0, 2),
  };
  const Schedule schedule = trader::paper_batch::build_schedule(
      updates, {}, DependencyGraphMode::UpdateEdgesOnly);
  require(schedule.dags.size() >= 2,
          "a directed cycle cannot remain in one DAG");
  require(trader::paper_batch::has_cross_dag_vertex_overlap(schedule.dags),
          "cycle split must expose shared-vertex cross-DAG risk");
  validate_all_dags(schedule);
}

void test_disconnected_components_are_covered() {
  ++tests_run;
  const std::vector<EdgeUpdate> updates = {
      update(1, 2, 1.0, 0),
      update(2, 3, 1.0, 1),
      update(10, 11, 1.0, 2),
      update(11, 12, 1.0, 3),
  };
  const Schedule schedule = trader::paper_batch::build_schedule(
      updates, {}, DependencyGraphMode::UpdateEdgesOnly);
  validate_all_dags(schedule);
}

void test_two_dependency_graph_readings_are_explicit() {
  ++tests_run;
  const std::vector<EdgeUpdate> updates = {
      update(1, 2, -1.0, 0),
      update(3, 4, -2.0, 1, true),
  };
  const std::vector<DirectedEdge> existing = {
      {2, 3}, {4, 1}, {4, 99}, {99, 1}, {1, 2},
  };
  const Schedule update_only = trader::paper_batch::build_schedule(
      updates, existing, DependencyGraphMode::UpdateEdgesOnly);
  const Schedule induced = trader::paper_batch::build_schedule(
      updates, existing, DependencyGraphMode::VertexInduced);

  require(update_only.dependency_edges.size() == 2,
          "update-edge-only mode must exclude unchanged graph edges");
  require(induced.dependency_edges.size() == 4,
          "vertex-induced mode must include existing edges among endpoints");
  require(std::find(induced.dependency_edges.begin(),
                    induced.dependency_edges.end(),
                    DirectedEdge{2, 3}) != induced.dependency_edges.end(),
          "induced edge 2->3 must be present");
  require(std::find(induced.dependency_edges.begin(),
                    induced.dependency_edges.end(),
                    DirectedEdge{4, 99}) == induced.dependency_edges.end(),
          "edge touching a non-batch endpoint must be excluded");
  require(std::find(induced.dependency_edges.begin(),
                    induced.dependency_edges.end(),
                    DirectedEdge{3, 4}) != induced.dependency_edges.end(),
          "a deletion update remains a scheduling dependency");
  validate_all_dags(update_only);
  validate_all_dags(induced);
}

void test_deterministic_tie_rules() {
  ++tests_run;
  const std::vector<EdgeUpdate> updates = {
      update(5, 7, 1.0, 0),
      update(1, 3, 1.0, 1),
      update(5, 6, 1.0, 2),
      update(1, 2, 1.0, 3),
  };
  const std::vector<DirectedEdge> existing_a = {
      {7, 1},
      {3, 5},
      {2, 6},
  };
  std::vector<DirectedEdge> existing_b = existing_a;
  std::reverse(existing_b.begin(), existing_b.end());

  const Schedule first = trader::paper_batch::build_schedule(
      updates, existing_a, DependencyGraphMode::VertexInduced);
  const Schedule second = trader::paper_batch::build_schedule(
      updates, existing_b, DependencyGraphMode::VertexInduced);
  require(fingerprint(first) == fingerprint(second),
          "container iteration order must not alter the schedule");
  validate_all_dags(first);
}

void test_self_loop_is_rejected() {
  ++tests_run;
  bool rejected = false;
  try {
    (void)trader::paper_batch::build_schedule(
        {update(1, 1, -1.0, 0)}, {}, DependencyGraphMode::UpdateEdgesOnly);
  } catch (const std::invalid_argument &) {
    rejected = true;
  }
  require(rejected, "self-loop must not silently enter a DAG");
}

} // namespace

int main() {
  test_empty_batch();
  test_coalescing_is_last_write_wins();
  test_chain_orders_forward_and_backward();
  test_multi_parent_and_multi_successor_dependencies();
  test_directed_cycle_is_split_without_losing_edges();
  test_disconnected_components_are_covered();
  test_two_dependency_graph_readings_are_explicit();
  test_deterministic_tie_rules();
  test_self_loop_is_rejected();
  std::cout << "BL-1 passed: " << tests_run
            << " deterministic scheduler cases.\n";
  return 0;
}
