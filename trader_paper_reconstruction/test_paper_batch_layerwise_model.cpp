#include "paper_batch_layerwise_model.h"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <random>
#include <string>
#include <tuple>
#include <vector>

namespace {

using trader::paper_batch::ColorMap;
using trader::paper_batch::DependencyGraphMode;
using trader::paper_batch::DirectedWeightedGraph;
using trader::paper_batch::EdgeUpdate;
using trader::paper_batch::LayerwiseBatchApplication;
using trader::paper_batch::PaperLayerwiseBatchMaintainer;
using trader::paper_batch::SchedulePolicy;
using trader::paper_batch::StateTable;
using trader::paper_batch::TieBreakDirection;
using trader::paper_batch::VertexId;

int suites = 0;
int generated_checkpoints = 0;

void require(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "BL-4 failure: " << message << '\n';
    std::abort();
  }
}

EdgeUpdate update(VertexId source, VertexId destination, double weight,
                  std::size_t arrival, bool erase = false) {
  return {
      source, destination, weight, erase, "event-" + std::to_string(arrival),
      arrival};
}

void add_edges(
    DirectedWeightedGraph &graph,
    const std::vector<std::tuple<VertexId, VertexId, double>> &edges) {
  for (const auto &[source, destination, weight] : edges) {
    graph.set_edge(source, destination, weight);
  }
}

void require_oracle_match(const PaperLayerwiseBatchMaintainer &maintainer,
                          const std::string &context) {
  const StateTable oracle = trader::paper_batch::enumerate_state_oracle(
      maintainer.graph(), maintainer.colors(), maintainer.hop_bound());
  const auto comparison =
      trader::paper_batch::compare_state_tables(oracle, maintainer.states());
  require(comparison.equal,
          context + ": state mismatch: " + comparison.first_difference);

  const auto expected_answer = trader::paper_batch::enumerate_cycle_oracle(
      maintainer.graph(), maintainer.colors(), maintainer.hop_bound());
  const auto actual_answer = maintainer.answer();
  require(expected_answer.exists == actual_answer.exists,
          context + ": answer existence mismatch");
  if (expected_answer.exists) {
    require(std::abs(expected_answer.weight - actual_answer.weight) <= 1e-12,
            context + ": answer weight mismatch");
    require(expected_answer.cycle == actual_answer.cycle,
            context + ": answer witness mismatch");
  }
}

void require_application_contract(const LayerwiseBatchApplication &application,
                                  const std::string &context) {
  require(application.effective_update_coverage,
          context + ": effective edge not applied exactly once per direction");
  require(application.forward_applied_updates.size() ==
              application.effective_updates.size(),
          context + ": forward apply count mismatch");
  require(application.backward_applied_updates.size() ==
              application.effective_updates.size(),
          context + ": backward apply count mismatch");
  require(application.every_state_processed_at_most_once,
          context + ": DP state was revisited in a layer-wise pass");
  require(application.queued_state_keys == application.processed_state_keys,
          context + ": queued DP state was not processed");
}

void test_coalesced_dag_queue_contract() {
  ++suites;
  DirectedWeightedGraph graph;
  for (VertexId vertex = 0; vertex < 5; ++vertex) {
    graph.add_vertex(vertex);
  }
  add_edges(graph, {{0, 1, 2.0},
                    {1, 2, 2.0},
                    {2, 0, 2.0},
                    {2, 3, 2.0},
                    {3, 4, 2.0},
                    {4, 2, 2.0}});
  const ColorMap colors{{0, 0}, {1, 1}, {2, 2}, {3, 0}, {4, 1}};
  PaperLayerwiseBatchMaintainer maintainer(graph, colors, 3);
  const auto application =
      maintainer.apply_batch({update(0, 1, -1.0, 0), update(0, 1, -2.0, 1),
                              update(1, 2, -2.0, 2), update(2, 0, -2.0, 3)},
                             DependencyGraphMode::UpdateEdgesOnly);
  require(application.schedule.coalesced_updates.size() == 3,
          "same directed edge must retain only the final update");
  require(application.schedule.dags.size() >= 2,
          "cyclic update edges must be split into multiple DAGs");
  require(application.cross_dag_vertex_overlap,
          "cycle split must expose cross-DAG vertex overlap");
  require_application_contract(application, "coalesced DAG queue");
  require_oracle_match(maintainer, "coalesced DAG queue");
}

void test_increase_deletion_and_alternative_paths() {
  ++suites;
  DirectedWeightedGraph graph;
  add_edges(graph,
            {{0, 1, 0.0}, {1, 2, 0.0}, {0, 3, 1.0}, {3, 2, 1.0}, {2, 0, 0.0}});
  const ColorMap colors{{0, 0}, {1, 1}, {2, 2}, {3, 1}};
  PaperLayerwiseBatchMaintainer maintainer(graph, colors, 3);

  auto application = maintainer.apply_batch(
      {update(1, 2, 10.0, 0)}, DependencyGraphMode::UpdateEdgesOnly);
  require(application.backward_invalidation_seeds > 0,
          "weight increase must invalidate at least one selected witness");
  require_application_contract(application, "weight increase");
  require_oracle_match(maintainer, "weight increase");
  require(std::abs(maintainer.answer().weight - 2.0) <= 1e-12,
          "weight increase must select the alternative path");

  application = maintainer.apply_batch({update(3, 2, 0.0, 1, true)},
                                       DependencyGraphMode::VertexInduced);
  require_application_contract(application, "edge deletion");
  require_oracle_match(maintainer, "edge deletion");
  require(maintainer.answer().exists &&
              std::abs(maintainer.answer().weight - 10.0) <= 1e-12,
          "deleting the alternative path must leave the positive cycle");
}

void test_two_updated_edges_create_one_new_path() {
  ++suites;
  DirectedWeightedGraph graph;
  for (VertexId vertex = 0; vertex < 4; ++vertex) {
    graph.add_vertex(vertex);
  }
  graph.set_edge(2, 0, 0.0);
  graph.set_edge(0, 3, 5.0);
  graph.set_edge(3, 2, 5.0);
  const ColorMap colors{{0, 0}, {1, 1}, {2, 2}, {3, 1}};
  PaperLayerwiseBatchMaintainer maintainer(graph, colors, 3);
  const auto application =
      maintainer.apply_batch({update(0, 1, -2.0, 0), update(1, 2, -2.0, 1)},
                             DependencyGraphMode::UpdateEdgesOnly);
  require(application.forward_candidate_seeds > 0,
          "insertions must seed forward DP candidates");
  require_application_contract(application, "two-edge insertion");
  require_oracle_match(maintainer, "two-edge insertion");
  require(std::abs(maintainer.answer().weight - (-4.0)) <= 1e-12,
          "two inserted edges must form the new best cycle");
}

void test_selected_witness_repair_and_stale_proposal() {
  ++suites;
  for (const auto mode : {DependencyGraphMode::UpdateEdgesOnly,
                          DependencyGraphMode::VertexInduced}) {
    DirectedWeightedGraph graph;
    add_edges(graph, {{0, 1, 0}, {1, 2, 5}, {0, 3, 0}, {3, 2, 0}});
    const ColorMap colors{{0, 0}, {1, 1}, {2, 2}, {3, 1}, {4, 3}};
    PaperLayerwiseBatchMaintainer maintainer(graph, colors, 4);
    auto application = maintainer.apply_batch({update(1, 2, 6, 0)}, mode);
    require_application_contract(application, "unused predecessor increase");
    require_oracle_match(maintainer, "unused predecessor increase");
    require(application.processed_state_keys == 1,
            "an unused incoming edge must not force an unchanged optimum to recompute");

    // The inserted edge initially receives an improving proposal using a
    // pre-batch prefix. That prefix is worsened elsewhere in this same batch.
    DirectedWeightedGraph mixed;
    add_edges(mixed, {{0, 1, 0}, {1, 2, 0}, {0, 3, 10}, {3, 2, 0}});
    PaperLayerwiseBatchMaintainer mixed_maintainer(mixed, colors, 4);
    application = mixed_maintainer.apply_batch(
        {update(1, 2, 20, 0), update(2, 4, 0, 1)}, mode);
    require_application_contract(application, "stale mixed-batch proposal");
    require_oracle_match(mixed_maintainer, "stale mixed-batch proposal");
    const auto &value = mixed_maintainer.states().at({0, 4, 15});
    require(value.weight == 10 && value.path == std::vector<VertexId>({0, 3, 2, 4}),
            "repair must invalidate stale proposals, including previously absent states");
  }
}

void test_converging_improvements_share_one_queue_key() {
  ++suites;
  DirectedWeightedGraph graph;
  add_edges(graph, {{0, 1, 10}, {0, 3, 10}, {1, 2, 0}, {3, 2, 0}});
  const ColorMap colors{{0, 0}, {1, 1}, {2, 2}, {3, 1}};
  PaperLayerwiseBatchMaintainer maintainer(graph, colors, 3);
  const auto application = maintainer.apply_batch(
      {update(0, 1, 5, 0), update(0, 3, 4, 1)}, DependencyGraphMode::UpdateEdgesOnly);
  require_application_contract(application, "converging improvements");
  require_oracle_match(maintainer, "converging improvements");
  require(application.queued_state_keys == 3 && application.processed_state_keys == 3,
          "two proposals for one successor must share one queue entry");
  const auto &value = maintainer.states().at({0, 2, 7});
  require(value.weight == 4 && value.path == std::vector<VertexId>({0, 3, 2}),
          "deduplicated successor must retain the best incoming proposal");
  const auto mixed = maintainer.apply_batch(
      {update(0, 1, 3, 2), update(0, 3, 12, 3)}, DependencyGraphMode::UpdateEdgesOnly);
  require_application_contract(mixed, "shared successor repair and proposal");
  require_oracle_match(maintainer, "shared successor repair and proposal");
  require(maintainer.states().at({0, 2, 7}).weight == 3,
          "one queue entry must retain both repair and improving proposal");
  const auto deleted = maintainer.apply_batch(
      {update(0, 1, 0, 4, true)}, DependencyGraphMode::UpdateEdgesOnly);
  require_application_contract(deleted, "shared successor after deletion");
  require_oracle_match(maintainer, "shared successor after deletion");
  require(maintainer.states().at({0, 2, 7}).weight == 12,
          "a later batch must repair the successor using its remaining path");
}

std::vector<SchedulePolicy> all_policies() {
  std::vector<SchedulePolicy> result;
  for (const auto vertex_ties :
       {TieBreakDirection::Ascending, TieBreakDirection::Descending}) {
    for (const auto edge_ties :
         {TieBreakDirection::Ascending, TieBreakDirection::Descending}) {
      for (const auto topological_ties :
           {TieBreakDirection::Ascending, TieBreakDirection::Descending}) {
        for (const bool reverse_dags : {false, true}) {
          result.push_back(
              {vertex_ties, edge_ties, topological_ties, reverse_dags});
        }
      }
    }
  }
  return result;
}

void test_layerwise_result_is_independent_of_legal_ties() {
  ++suites;
  DirectedWeightedGraph graph;
  for (VertexId vertex = 0; vertex < 7; ++vertex) {
    graph.add_vertex(vertex);
  }
  add_edges(graph, {{0, 1, 1.0},
                    {1, 2, 1.0},
                    {2, 0, 1.0},
                    {0, 3, 2.0},
                    {3, 2, 2.0},
                    {2, 4, 1.0},
                    {4, 5, 1.0},
                    {5, 2, 1.0},
                    {1, 6, 1.0},
                    {6, 0, 1.0}});
  const ColorMap colors{{0, 0}, {1, 1}, {2, 2}, {3, 1}, {4, 0}, {5, 1}, {6, 2}};
  const std::vector<EdgeUpdate> updates{
      update(0, 1, -2.0, 0), update(1, 2, -2.0, 1), update(2, 0, -2.0, 2),
      update(2, 4, -1.0, 3), update(4, 5, -1.0, 4), update(5, 2, -1.0, 5),
      update(1, 6, 4.0, 6)};

  StateTable reference;
  bool have_reference = false;
  for (const SchedulePolicy &policy : all_policies()) {
    PaperLayerwiseBatchMaintainer maintainer(graph, colors, 3);
    const auto application = maintainer.apply_batch(
        updates, DependencyGraphMode::UpdateEdgesOnly, policy);
    require_application_contract(application, "legal tie policy");
    require_oracle_match(maintainer, "legal tie policy");
    if (!have_reference) {
      reference = maintainer.states();
      have_reference = true;
    } else {
      const auto comparison = trader::paper_batch::compare_state_tables(
          reference, maintainer.states());
      require(comparison.equal,
              "legal Algorithm 3 tie choices changed the final DP state");
    }
  }
}

void test_fixed_seed_generated_batches() {
  ++suites;
  std::mt19937 generator(20260904U);
  std::uniform_int_distribution<int> weight(-4, 6);
  std::uniform_int_distribution<int> vertex(0, 6);
  std::bernoulli_distribution edge_present(0.32);

  for (const std::uint32_t hop_bound : {3U, 4U}) {
    for (int graph_index = 0; graph_index < 18; ++graph_index) {
      DirectedWeightedGraph graph;
      ColorMap colors;
      for (VertexId id = 0; id < 7; ++id) {
        graph.add_vertex(id);
        colors[id] = id % hop_bound;
      }
      for (VertexId source = 0; source < 7; ++source) {
        for (VertexId destination = 0; destination < 7; ++destination) {
          if (source != destination && edge_present(generator)) {
            graph.set_edge(source, destination,
                           static_cast<double>(weight(generator)));
          }
        }
      }

      PaperLayerwiseBatchMaintainer maintainer(graph, colors, hop_bound);
      require_oracle_match(maintainer,
                           "generated initial " + std::to_string(graph_index));
      for (int batch_index = 0; batch_index < 8; ++batch_index) {
        std::vector<EdgeUpdate> updates;
        for (int item = 0; item < 4; ++item) {
          VertexId source = static_cast<VertexId>(vertex(generator));
          VertexId destination = static_cast<VertexId>(vertex(generator));
          while (destination == source) {
            destination = static_cast<VertexId>(vertex(generator));
          }
          const std::size_t arrival =
              static_cast<std::size_t>(batch_index * 10 + item);
          updates.push_back(update(source, destination,
                                   static_cast<double>(weight(generator)),
                                   arrival, item == 3 && batch_index % 4 == 0));
          if (item == 1 && batch_index % 3 == 0) {
            updates.push_back(update(source, destination,
                                     static_cast<double>(weight(generator)),
                                     arrival + 5));
          }
        }
        const auto application = maintainer.apply_batch(
            updates, batch_index % 2 == 0 ? DependencyGraphMode::UpdateEdgesOnly
                                          : DependencyGraphMode::VertexInduced);
        const std::string context = "generated k=" + std::to_string(hop_bound) +
                                    " graph=" + std::to_string(graph_index) +
                                    " batch=" + std::to_string(batch_index);
        require_application_contract(application, context);
        require_oracle_match(maintainer, context);
        ++generated_checkpoints;
      }
    }
  }
}

void test_repair_selects_prefix_before_materializing_path() {
  ++suites;
  DirectedWeightedGraph graph;
  for (VertexId v = 0; v < 5; ++v) graph.add_vertex(v);
  add_edges(graph, {{0, 1, 0}, {0, 2, 0}, {0, 3, 0},
                    {1, 4, 3}, {2, 4, 2}, {3, 4, 1}, {4, 0, 0}});
  PaperLayerwiseBatchMaintainer model(graph, {{0, 0}, {1, 1}, {2, 1}, {3, 1}, {4, 2}}, 3);
  const auto check = [&](VertexId middle, const std::string &label) {
    require_oracle_match(model, label);
    const auto state = model.states().find({0, 4, 7});
    require(state != model.states().end() &&
            state->second.path == std::vector<VertexId>({0, middle, 4}), label);
  };
  check(3, "initial winner");
  model.apply_batch({update(3, 4, 10, 1)}, DependencyGraphMode::UpdateEdgesOnly);
  check(2, "repair replaces its first candidate with a better prefix");
  model.apply_batch({update(2, 4, 3, 2)}, DependencyGraphMode::UpdateEdgesOnly);
  check(1, "equal-weight repair preserves lexicographic witness");
  model.apply_batch({update(1, 4, 0, 3, true)}, DependencyGraphMode::UpdateEdgesOnly);
  check(2, "deletion selects remaining equal-weight prefix");
}

} // namespace

int main() {
  test_repair_selects_prefix_before_materializing_path();
  test_coalesced_dag_queue_contract();
  test_increase_deletion_and_alternative_paths();
  test_two_updated_edges_create_one_new_path();
  test_selected_witness_repair_and_stale_proposal();
  test_converging_improvements_share_one_queue_key();
  test_layerwise_result_is_independent_of_legal_ties();
  test_fixed_seed_generated_batches();
  std::cout << "BL-4 passed: " << suites << " suites, including "
            << generated_checkpoints
            << " generated checkpoints, with Algorithm-3 queue coverage and "
               "complete state/answer-oracle equality.\n";
  return 0;
}
