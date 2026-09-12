#include "paper_edge_grouping.h"
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#ifdef TRADER_PROFILE
#include <cmath>
#endif
#ifdef _WIN32
#include <windows.h>
#include <psapi.h>
#endif
using namespace trader::paper_batch;
using Clock = std::chrono::steady_clock;
double ms(Clock::time_point a, Clock::time_point b) {
  return std::chrono::duration<double,std::milli>(b-a).count();
}
int main(int argc, char** argv) { try {
  if (argc != 6) throw std::invalid_argument("case k ell update-only|vertex-induced trace");
  const std::string folder = argv[1], mode_name = argv[4];
  const auto k = std::stoul(argv[2]), ell = std::stoul(argv[3]);
  if (k < 2 || k > 63 || !ell) throw std::invalid_argument("invalid k/ell");
  const auto mode = mode_name == "update-only" ? DependencyGraphMode::UpdateEdgesOnly : DependencyGraphMode::VertexInduced;
  if (mode_name != "update-only" && mode_name != "vertex-induced") throw std::invalid_argument("unknown DAG mode");
  std::vector<ColorMap> maps;
  for (std::size_t trial = 0; trial < ell; ++trial) {
    std::ifstream input(folder + (trial ? "/colors_"+std::to_string(trial)+".txt" : "/colors.txt"));
    if (!input) throw std::runtime_error("missing color file");
    ColorMap colors; std::uint32_t value, vertex = 0;
    while (input >> value) colors[vertex++] = value;
    if (colors.empty() || (!maps.empty() && colors.size() != maps.front().size())) throw std::runtime_error("color dimensions mismatch");
    maps.push_back(std::move(colors));
  }
  auto initial = Clock::now(); DirectedWeightedGraph graph;
  for (const auto& [vertex,color] : maps.front()) { (void)color; graph.add_vertex(vertex); }
  std::ifstream input_graph(folder+"/graph.txt");
  if (!input_graph) throw std::runtime_error("missing graph");
  std::uint32_t u,v; double w;
  while (input_graph >> u >> v >> w) graph.set_edge(u,v,w);
  if (!input_graph.eof()) throw std::runtime_error("malformed graph");
  std::vector<std::unique_ptr<PaperEdgeGrouping>> engines;
  for (std::size_t i = 0; i < ell; ++i) {
    engines.push_back(std::make_unique<PaperEdgeGrouping>(graph,maps[i],k,mode));
    std::cerr << "INITIALIZING " << i+1 << '/' << ell << '\n';
  }
  auto initialized = Clock::now();
  std::cerr << "INITIALIZED ell=" << ell << " init_ms=" << ms(initial,initialized) << '\n';
  auto answer = [&] {
    CycleAnswer best; std::size_t selected = 0;
    for (std::size_t i = 0; i < engines.size(); ++i) {
      auto candidate = engines[i]->answer();
      if (candidate.exists && (!best.exists || candidate.weight < best.weight)) { best = std::move(candidate); selected = i; }
    }
    return std::make_pair(best, selected);
  };
  std::ofstream trace(argv[5]); if (!trace) throw std::runtime_error("trace output");
  trace << std::setprecision(17) << "row\tweight\tpath\tcoloring\n";
  auto emit = [&](std::size_t row, const auto& selected) {
    trace << row << '\t'; if (selected.first.exists) trace << selected.first.weight; else trace << "none";
    trace << '\t'; for (std::size_t i = 0; i < selected.first.cycle.size(); ++i) trace << (i ? " " : "") << selected.first.cycle[i];
    trace << '\t' << selected.second << '\n';
  };
  emit(0,answer());
  std::size_t rows = 0, batches = 0, deferred = 0, states_processed = 0;
#ifdef TRADER_PROFILE
  double snapshot_ms = 0, dp_ms = 0, candidate_ms = 0;
  std::vector<double> cumulative(ell, 0);
  std::ostringstream events;
  events << std::setprecision(17);
  auto profile = [&](const GroupingEvent& event) {
    snapshot_ms += event.snapshot_ms; dp_ms += event.dp_ms; candidate_ms += event.candidate_ms;
  };
  auto record_event = [&](std::size_t row, std::size_t trial, const char* reason,
                          const GroupingEvent& event, double elapsed) {
    cumulative[trial] += event.adverse_change;
    auto number = [&](double value) {
      if (std::isfinite(value)) events << value;
      else events << "\"" << (value < 0 ? "-inf" : "inf") << "\"";
    };
    events << "{\"row\":" << row << ",\"coloring\":" << trial
           << ",\"reason\":\"" << reason << "\",\"maintained\":" << (event.maintained ? "true" : "false")
           << ",\"batch_size\":" << event.batch_size
           << ",\"coalesced_size\":" << event.layerwise.schedule.coalesced_updates.size()
           << ",\"effective_updates\":" << event.layerwise.effective_updates.size()
           << ",\"states_processed\":" << event.layerwise.processed_state_keys
           << ",\"gap_before\":"; number(event.gap_before);
    events << ",\"cumulative_adverse\":"; number(cumulative[trial]);
    events << ",\"update_ms\":" << elapsed << ",\"snapshot_ms\":" << event.snapshot_ms
           << ",\"dp_ms\":" << event.dp_ms << ",\"candidate_ms\":" << event.candidate_ms
           << ",\"dp_setup_ms\":" << event.layerwise.setup_ms
           << ",\"dp_seed_ms\":" << event.layerwise.seed_ms
           << ",\"dp_propagation_ms\":" << event.layerwise.propagation_ms
           << ",\"seed_prefixes_examined\":" << event.layerwise.seed_prefixes_examined
           << ",\"proposal_attempts\":" << event.layerwise.proposal_attempts
           << ",\"repair_requests\":" << event.layerwise.repair_requests
           << ",\"repair_states\":" << event.layerwise.repair_states
           << ",\"proposal_states\":" << event.layerwise.proposal_states
           << ",\"changed_states\":" << event.layerwise.changed_state_keys
           << ",\"incoming_edges_scanned\":" << event.layerwise.incoming_edges_scanned
           << ",\"incoming_state_lookups\":" << event.layerwise.incoming_state_lookups << "}\n";
    if (event.maintained) cumulative[trial] = 0;
  };
#endif
  double core = 0; auto begin = Clock::now();
  std::ifstream updates(folder+"/updates.txt"); if (!updates) throw std::runtime_error("missing updates");
  std::string line;
  while (std::getline(updates,line)) {
    std::istringstream row(line); std::string token;
    if (!(row >> u >> v >> token)) throw std::runtime_error("malformed update");
    if (token == "D") throw std::runtime_error("deletion outside common formal domain");
    ++rows; auto start = Clock::now();
    if (token != "N") {
      const EdgeUpdate update{u,v,std::stod(token),false,std::to_string(rows),rows};
      for (std::size_t trial = 0; trial < engines.size(); ++trial) {
        auto& engine = engines[trial];
#ifdef TRADER_PROFILE
        const bool is_new = !engine->live_graph().has_edge(u,v);
        const bool has_candidate = engine->candidates() != 0;
        const auto event_start = Clock::now();
#endif
        auto event = engine->update(update);
#ifdef TRADER_PROFILE
        const double event_ms = ms(event_start,Clock::now());
        profile(event);
        const char* reason = event.maintained ? (is_new ? "new_edge" : (!has_candidate ? "no_candidate" : "gap_exceeded"))
                           : (event.deferred ? "deferred" : "no_change");
        record_event(rows,trial,reason,event,event_ms);
#endif
        batches += event.maintained; deferred += event.deferred;
        states_processed += event.layerwise.processed_state_keys;
      }
    }
#ifdef TRADER_PROFILE
    else for (std::size_t trial = 0; trial < engines.size(); ++trial)
      record_event(rows,trial,"input_N",GroupingEvent{},0);
#endif
    const auto best = answer(); core += ms(start,Clock::now()); emit(rows,best);
  }
  // Explicit completion rule: flush deferred work at EOF; cost stays online.
  auto start = Clock::now();
  for (std::size_t trial = 0; trial < engines.size(); ++trial) {
#ifdef TRADER_PROFILE
    const auto event_start = Clock::now();
#endif
    auto event = engines[trial]->flush(); batches += event.maintained; states_processed += event.layerwise.processed_state_keys;
#ifdef TRADER_PROFILE
    const double event_ms = ms(event_start,Clock::now());
    profile(event);
    record_event(rows,trial,"eof_flush",event,event_ms);
#endif
  }
  core += ms(start,Clock::now()); trace.flush(); updates.close(); auto end = Clock::now();
#ifdef TRADER_PROFILE
  // Diagnostic records are buffered in memory and written after online timing.
  // Profiling results must still remain separate from formal release timings.
  std::ofstream event_output(std::string(argv[5])+".eg.jsonl");
  if (!event_output) throw std::runtime_error("EG diagnostic output");
  event_output << events.str();
#endif
  std::size_t candidates = 0, states = 0;
  for (const auto& engine : engines) { candidates += engine->candidates(); states += engine->model().states().size(); }
  double peak_mib = 0;
#ifdef _WIN32
  PROCESS_MEMORY_COUNTERS memory{};
  if (!GetProcessMemoryInfo(GetCurrentProcess(),&memory,sizeof(memory))) throw std::runtime_error("peak memory query failed");
  peak_mib = double(memory.PeakWorkingSetSize)/1048576;
#endif
  std::cout << std::setprecision(17) << "{\"method\":\"TRADER-paper-reconstructed-EG\",\"init_ms\":" << ms(initial,initialized)
            << ",\"online_ms\":" << ms(begin,end) << ",\"core_ms\":" << core << ",\"rows\":" << rows
            << ",\"queries\":" << rows << ",\"ell\":" << ell << ",\"peak_rss_mib\":";
#ifdef _WIN32
  std::cout << peak_mib;
#else
  std::cout << "null";
#endif
  std::cout << ",\"maintenance_batches\":" << batches << ",\"deferred_instance_updates\":" << deferred
            << ",\"dp_states_processed\":" << states_processed << ",\"candidate_cycles\":" << candidates
            << ",\"states\":" << states << ",\"grouping_scope\":\"per_coloring\",\"dag_mode\":\"" << mode_name << "\"";
#ifdef TRADER_PROFILE
  std::cout << ",\"profiled\":true,\"snapshot_ms\":" << snapshot_ms << ",\"dp_ms\":" << dp_ms << ",\"candidate_ms\":" << candidate_ms;
#endif
  std::cout << "}\n";
  return 0;
} catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; } }
