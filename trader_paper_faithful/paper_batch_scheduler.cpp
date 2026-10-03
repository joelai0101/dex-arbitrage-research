#include "paper_batch_scheduler.h"

#include <algorithm>
#include <map>
#include <queue>
#include <set>
#include <stdexcept>
#include <tuple>
#include <unordered_map>
#include <unordered_set>

namespace trader::paper_batch {
namespace {

using EdgeKey = std::pair<VertexId, VertexId>;

EdgeKey key_of(const DirectedEdge &edge) {
  return {edge.source, edge.destination};
}

EdgeKey key_of(const EdgeUpdate &update) {
  return {update.source, update.destination};
}

bool reaches(
    VertexId start, VertexId target,
    const std::unordered_map<VertexId, std::vector<VertexId>> &adjacency) {
  if (start == target) {
    return true;
  }

  std::queue<VertexId> pending;
  std::unordered_set<VertexId> visited;
  pending.push(start);
  visited.insert(start);
  while (!pending.empty()) {
    const VertexId current = pending.front();
    pending.pop();
    const auto found = adjacency.find(current);
    if (found == adjacency.end()) {
      continue;
    }
    for (const VertexId next : found->second) {
      if (next == target) {
        return true;
      }
      if (visited.insert(next).second) {
        pending.push(next);
      }
    }
  }
  return false;
}

std::vector<VertexId>
sorted_vertices_by_total_degree(const std::vector<DirectedEdge> &edges,
                                TieBreakDirection tie_direction) {
  std::unordered_map<VertexId, std::size_t> degree;
  for (const DirectedEdge &edge : edges) {
    ++degree[edge.source];
    ++degree[edge.destination];
  }

  std::vector<VertexId> vertices;
  vertices.reserve(degree.size());
  for (const auto &[vertex, ignored] : degree) {
    (void)ignored;
    vertices.push_back(vertex);
  }
  std::sort(vertices.begin(), vertices.end(), [&](VertexId lhs, VertexId rhs) {
    if (degree.at(lhs) != degree.at(rhs)) {
      return degree.at(lhs) > degree.at(rhs);
    }
    return tie_direction == TieBreakDirection::Ascending ? lhs < rhs
                                                         : lhs > rhs;
  });
  return vertices;
}

std::unordered_map<VertexId, std::size_t>
topological_rank(const Dag &dag, const std::vector<DirectedEdge> &edges,
                 TieBreakDirection tie_direction) {
  std::unordered_map<VertexId, std::size_t> indegree;
  std::unordered_map<VertexId, std::vector<VertexId>> adjacency;
  for (const VertexId vertex : dag.vertices) {
    indegree.emplace(vertex, 0);
  }
  for (const std::size_t index : dag.edge_indices) {
    const DirectedEdge &edge = edges.at(index);
    adjacency[edge.source].push_back(edge.destination);
    ++indegree[edge.destination];
  }
  for (auto &[ignored, destinations] : adjacency) {
    (void)ignored;
    std::sort(destinations.begin(), destinations.end());
  }

  std::priority_queue<VertexId> descending_ready;
  std::priority_queue<VertexId, std::vector<VertexId>, std::greater<VertexId>>
      ascending_ready;
  for (const auto &[vertex, count] : indegree) {
    if (count == 0) {
      if (tie_direction == TieBreakDirection::Ascending) {
        ascending_ready.push(vertex);
      } else {
        descending_ready.push(vertex);
      }
    }
  }

  std::unordered_map<VertexId, std::size_t> rank;
  std::size_t next_rank = 0;
  while (!ascending_ready.empty() || !descending_ready.empty()) {
    VertexId current = 0;
    if (tie_direction == TieBreakDirection::Ascending) {
      current = ascending_ready.top();
      ascending_ready.pop();
    } else {
      current = descending_ready.top();
      descending_ready.pop();
    }
    rank[current] = next_rank++;
    for (const VertexId next : adjacency[current]) {
      auto found = indegree.find(next);
      if (found == indegree.end() || found->second == 0) {
        throw std::runtime_error("invalid DAG indegree state");
      }
      --found->second;
      if (found->second == 0) {
        if (tie_direction == TieBreakDirection::Ascending) {
          ascending_ready.push(next);
        } else {
          descending_ready.push(next);
        }
      }
    }
  }

  if (rank.size() != dag.vertices.size()) {
    throw std::runtime_error("topological sort received a cyclic graph");
  }
  return rank;
}

std::vector<std::size_t> positions_of(const std::vector<std::size_t> &order,
                                      std::size_t edge_count) {
  std::vector<std::size_t> position(edge_count, edge_count);
  for (std::size_t index = 0; index < order.size(); ++index) {
    position.at(order[index]) = index;
  }
  return position;
}

} // namespace

std::vector<EdgeUpdate>
coalesce_latest(const std::vector<EdgeUpdate> &updates) {
  std::map<EdgeKey, EdgeUpdate> latest;
  for (const EdgeUpdate &update : updates) {
    if (update.source == update.destination) {
      throw std::invalid_argument(
          "paper batch scheduler does not support self-loop updates");
    }
    const EdgeKey key = key_of(update);
    const auto found = latest.find(key);
    if (found == latest.end() ||
        std::tie(found->second.arrival_index, found->second.event_id) <=
            std::tie(update.arrival_index, update.event_id)) {
      latest[key] = update;
    }
  }

  std::vector<EdgeUpdate> result;
  result.reserve(latest.size());
  for (const auto &[ignored, update] : latest) {
    (void)ignored;
    result.push_back(update);
  }
  std::sort(result.begin(), result.end(),
            [](const EdgeUpdate &lhs, const EdgeUpdate &rhs) {
              return std::tie(lhs.arrival_index, lhs.source, lhs.destination,
                              lhs.event_id) <
                     std::tie(rhs.arrival_index, rhs.source, rhs.destination,
                              rhs.event_id);
            });
  return result;
}

std::vector<DirectedEdge>
build_dependency_edges(const std::vector<EdgeUpdate> &coalesced_updates,
                       const std::vector<DirectedEdge> &existing_edges,
                       DependencyGraphMode mode) {
  std::set<DirectedEdge> unique_edges;
  std::set<VertexId> batch_vertices;
  for (const EdgeUpdate &update : coalesced_updates) {
    batch_vertices.insert(update.source);
    batch_vertices.insert(update.destination);
    // Definition V.1 uses E union B, so a deleted update edge remains a
    // structural dependency for scheduling this batch.
    unique_edges.insert({update.source, update.destination});
  }

  if (mode == DependencyGraphMode::VertexInduced) {
    for (const DirectedEdge &edge : existing_edges) {
      if (edge.source == edge.destination) {
        continue;
      }
      if (batch_vertices.count(edge.source) != 0 &&
          batch_vertices.count(edge.destination) != 0) {
        unique_edges.insert(edge);
      }
    }
  }

  return {unique_edges.begin(), unique_edges.end()};
}

std::vector<Dag> decompose_into_dags(const std::vector<DirectedEdge> &edges) {
  return decompose_into_dags(edges, SchedulePolicy{});
}

std::vector<Dag> decompose_into_dags(const std::vector<DirectedEdge> &edges,
                                     const SchedulePolicy &policy) {
  if (edges.empty()) {
    return {};
  }
  for (const DirectedEdge &edge : edges) {
    if (edge.source == edge.destination) {
      throw std::invalid_argument(
          "Algorithm 2 cannot place a self-loop in a DAG");
    }
  }

  const std::vector<VertexId> vertices =
      sorted_vertices_by_total_degree(edges, policy.vertex_ties);
  std::unordered_map<VertexId, std::vector<std::size_t>> outgoing;
  for (std::size_t index = 0; index < edges.size(); ++index) {
    outgoing[edges[index].source].push_back(index);
  }
  for (auto &[ignored, indices] : outgoing) {
    (void)ignored;
    std::sort(indices.begin(), indices.end(),
              [&](std::size_t lhs, std::size_t rhs) {
                if (policy.edge_ties == TieBreakDirection::Ascending) {
                  return key_of(edges.at(lhs)) < key_of(edges.at(rhs));
                }
                return key_of(edges.at(rhs)) < key_of(edges.at(lhs));
              });
  }

  std::vector<bool> assigned(edges.size(), false);
  std::size_t assigned_count = 0;
  std::vector<Dag> dags;
  while (assigned_count < edges.size()) {
    VertexId start = 0;
    bool found_start = false;
    for (const VertexId vertex : vertices) {
      const auto found = outgoing.find(vertex);
      if (found == outgoing.end()) {
        continue;
      }
      if (std::any_of(found->second.begin(), found->second.end(),
                      [&](std::size_t index) { return !assigned[index]; })) {
        start = vertex;
        found_start = true;
        break;
      }
    }
    if (!found_start) {
      throw std::runtime_error(
          "DAG decomposition left an edge without an outgoing source");
    }

    Dag dag;
    std::set<VertexId> dag_vertices;
    std::unordered_map<VertexId, std::vector<VertexId>> dag_adjacency;
    std::queue<VertexId> pending;
    std::unordered_set<VertexId> queued;
    pending.push(start);
    queued.insert(start);
    dag_vertices.insert(start);
    const std::size_t before = assigned_count;

    while (!pending.empty()) {
      const VertexId current = pending.front();
      pending.pop();
      const auto found = outgoing.find(current);
      if (found == outgoing.end()) {
        continue;
      }
      for (const std::size_t edge_index : found->second) {
        if (assigned[edge_index]) {
          continue;
        }
        const DirectedEdge &edge = edges.at(edge_index);
        if (reaches(edge.destination, edge.source, dag_adjacency)) {
          continue;
        }
        dag.edge_indices.push_back(edge_index);
        dag_vertices.insert(edge.source);
        dag_vertices.insert(edge.destination);
        dag_adjacency[edge.source].push_back(edge.destination);
        assigned[edge_index] = true;
        ++assigned_count;
        if (queued.insert(edge.destination).second) {
          pending.push(edge.destination);
        }
      }
    }

    if (assigned_count == before) {
      throw std::runtime_error("DAG decomposition made no progress");
    }
    dag.vertices.assign(dag_vertices.begin(), dag_vertices.end());
    if (!is_acyclic(dag, edges)) {
      throw std::runtime_error("Algorithm 2 produced a cyclic DAG");
    }
    dags.push_back(std::move(dag));
  }
  if (policy.reverse_dag_order) {
    std::reverse(dags.begin(), dags.end());
  }
  return dags;
}

std::vector<std::size_t>
forward_edge_order(const Dag &dag, const std::vector<DirectedEdge> &edges) {
  return forward_edge_order(dag, edges, TieBreakDirection::Ascending);
}

std::vector<std::size_t>
forward_edge_order(const Dag &dag, const std::vector<DirectedEdge> &edges,
                   TieBreakDirection topological_ties) {
  const auto rank = topological_rank(dag, edges, topological_ties);
  std::vector<std::size_t> order = dag.edge_indices;
  std::sort(order.begin(), order.end(), [&](std::size_t lhs, std::size_t rhs) {
    const DirectedEdge &left = edges.at(lhs);
    const DirectedEdge &right = edges.at(rhs);
    return std::make_tuple(rank.at(left.source), rank.at(left.destination),
                           left.source, left.destination) <
           std::make_tuple(rank.at(right.source), rank.at(right.destination),
                           right.source, right.destination);
  });
  return order;
}

std::vector<std::size_t>
backward_edge_order(const Dag &dag, const std::vector<DirectedEdge> &edges) {
  return backward_edge_order(dag, edges, TieBreakDirection::Ascending);
}

std::vector<std::size_t>
backward_edge_order(const Dag &dag, const std::vector<DirectedEdge> &edges,
                    TieBreakDirection topological_ties) {
  std::vector<std::size_t> order =
      forward_edge_order(dag, edges, topological_ties);
  std::reverse(order.begin(), order.end());
  return order;
}

Schedule build_schedule(const std::vector<EdgeUpdate> &updates,
                        const std::vector<DirectedEdge> &existing_edges,
                        DependencyGraphMode mode) {
  return build_schedule(updates, existing_edges, mode, SchedulePolicy{});
}

Schedule build_schedule(const std::vector<EdgeUpdate> &updates,
                        const std::vector<DirectedEdge> &existing_edges,
                        DependencyGraphMode mode,
                        const SchedulePolicy &policy) {
  Schedule result;
  result.mode = mode;
  result.policy = policy;
  result.coalesced_updates = coalesce_latest(updates);
  result.dependency_edges =
      build_dependency_edges(result.coalesced_updates, existing_edges, mode);
  result.dags = decompose_into_dags(result.dependency_edges, policy);
  return result;
}

bool is_acyclic(const Dag &dag, const std::vector<DirectedEdge> &edges) {
  try {
    (void)topological_rank(dag, edges, TieBreakDirection::Ascending);
    return true;
  } catch (const std::runtime_error &) {
    return false;
  }
}

bool covers_every_edge_exactly_once(const std::vector<Dag> &dags,
                                    std::size_t edge_count) {
  std::vector<std::size_t> counts(edge_count, 0);
  for (const Dag &dag : dags) {
    for (const std::size_t index : dag.edge_indices) {
      if (index >= edge_count) {
        return false;
      }
      ++counts[index];
    }
  }
  return std::all_of(counts.begin(), counts.end(),
                     [](std::size_t count) { return count == 1; });
}

bool respects_forward_dependencies(const Dag &dag,
                                   const std::vector<DirectedEdge> &edges) {
  const auto order = forward_edge_order(dag, edges);
  const auto position = positions_of(order, edges.size());
  for (const std::size_t current_index : dag.edge_indices) {
    const DirectedEdge &current = edges.at(current_index);
    for (const std::size_t predecessor_index : dag.edge_indices) {
      const DirectedEdge &predecessor = edges.at(predecessor_index);
      if (predecessor.destination == current.source &&
          position.at(predecessor_index) >= position.at(current_index)) {
        return false;
      }
    }
  }
  return true;
}

bool respects_backward_dependencies(const Dag &dag,
                                    const std::vector<DirectedEdge> &edges) {
  const auto order = backward_edge_order(dag, edges);
  const auto position = positions_of(order, edges.size());
  for (const std::size_t current_index : dag.edge_indices) {
    const DirectedEdge &current = edges.at(current_index);
    for (const std::size_t successor_index : dag.edge_indices) {
      const DirectedEdge &successor = edges.at(successor_index);
      if (successor.source == current.destination &&
          position.at(successor_index) >= position.at(current_index)) {
        return false;
      }
    }
  }
  return true;
}

bool has_cross_dag_vertex_overlap(const std::vector<Dag> &dags) {
  std::unordered_map<VertexId, std::size_t> first_dag;
  for (std::size_t dag_index = 0; dag_index < dags.size(); ++dag_index) {
    for (const VertexId vertex : dags[dag_index].vertices) {
      const auto [found, inserted] = first_dag.emplace(vertex, dag_index);
      if (!inserted && found->second != dag_index) {
        return true;
      }
    }
  }
  return false;
}

} // namespace trader::paper_batch
