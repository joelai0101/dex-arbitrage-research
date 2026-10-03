// Exercises the actual frozen persistent service, not a reimplemented EG rule.
#include <cmath>
#include <functional>
#include <iomanip>
#include <limits>
#include <set>
#include <sstream>
#include <string>
#include "cycle_detector.h"

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    int failed = 0;
    auto check = [&](const char* name, bool ok) {
        std::cout << "CHECK\t" << name << '\t' << (ok ? "PASS" : "FAIL") << '\n';
        failed += !ok;
    };
    auto make = [&](double gap = 100.0) {
        DirectedGraph graph;
        graph.load_edge_list(argv[1]);
        KCycleColorCoding service(graph, 5, 1, 10, 109, 1, true);
        service.common_start(109);
        service.regression_set_gap(gap); // Isolate accounting from known C2 defects.
        return service;
    };
    auto edge = [](const KCycleColorCoding& service, unsigned u, unsigned v) {
        const auto& graph = service.common_graph();
        auto [neighbors, weights, count] = graph.get_out_neighbors(u);
        for (unsigned i = 0; i < count; ++i)
            if (neighbors[i] == v) return weights[i];
        return std::numeric_limits<double>::infinity();
    };
    {
        auto s = make();
        check("fixture_best_cycle", s.common_weight() == -10 && s.common_path().size() == 6);
        const auto& colors = s.common_colors();
        std::set<int> first, second;
        for (unsigned i = 0; i < 5; ++i) {
            first.insert(colors.at(i));
            second.insert(colors.at(i + 5));
        }
        check("fixture_both_cycles_colorful", first.size() == 5 && second.size() == 5);
        s.common_apply("5 6 -4");
        check("decrease_retained", s.regression_decrease() == 3 && s.regression_pending() == 1);
        check("deferred_graph_unchanged", edge(s, 5, 6) == -1);
        s.common_finish();
        check("eof_installs_deferred", edge(s, 5, 6) == -4);
    }
    {
        auto s = make();
        s.common_apply("5 6 2");
        check("increase_not_decrease", s.regression_decrease() == 0 && s.regression_pending() == 1);
    }
    {
        auto s = make();
        s.common_apply("5 6 -1");
        check("equal_not_decrease", s.regression_decrease() == 0 && s.regression_pending() == 1);
        s.common_apply("5 6 N");
        check("noop_not_buffered", s.regression_decrease() == 0 && s.regression_pending() == 1);
    }
    {
        auto s = make();
        s.common_apply("5 6 -4");
        s.common_apply("5 6 -6");
        // Preserve upstream accounting against its unflushed graph: 3 + 5.
        check("repeated_edge_accounting", s.regression_decrease() == 8 && s.regression_pending() == 2);
        s.common_finish();
        check("repeated_edge_latest_value", edge(s, 5, 6) == -6);
    }
    {
        auto s = make(6);
        s.common_apply("5 6 -7");
        check("equal_gap_deferred", s.regression_decrease() == 6 && s.regression_pending() == 1);
        s.common_apply("6 7 -2");
        check("above_gap_flushes", s.regression_decrease() == 0 && s.regression_pending() == 0
              && edge(s, 5, 6) == -7 && edge(s, 6, 7) == -2);
    }
    {
        auto s = make();
        s.common_apply("5 6 -4");
        s.common_apply("5 7 -1");
        check("new_edge_flushes", s.regression_decrease() == 0 && s.regression_pending() == 0
              && edge(s, 5, 6) == -4 && edge(s, 5, 7) == -1);
    }
    {
        auto s = make();
        s.common_apply("0 1 -3");
        check("best_cycle_edge_immediate", s.regression_pending() == 0 && edge(s, 0, 1) == -3);
    }
#ifdef WITNESS_REGRESSION
    {
        auto s = make();
        s.common_apply("2 3 -3");
        check("backward_mask_includes_root", s.regression_endpoint_masks_valid());
    }
    {
        auto s = make();
        s.common_apply("4 0 -3");
        check("destination_zero_graph", edge(s, 4, 0) == -3);
        check("destination_zero_report", s.common_weight() == -11);
    }
    {
        auto s = make();
        unsigned same_color = 5;
        while (s.common_colors().at(same_color) != s.common_colors().at(0)) ++same_color;
        s.common_apply(std::to_string(same_color) + " 0 -7");
        check("same_color_destination_zero_graph", edge(s, same_color, 0) == -7);
    }
#endif
    // Report, but do not silently repair, the independently known gap failure.
    {
        DirectedGraph graph;
        graph.load_edge_list(argv[1]);
        KCycleColorCoding s(graph, 5, 1, 10, 109, 1, true);
        s.common_start(109);
        const double initial_gap = s.regression_gap();
        s.common_apply("5 6 -12");
        std::cout << std::setprecision(17) << "GAP_WITNESS\t" << initial_gap
                  << '\t' << s.common_weight() << '\t' << s.regression_pending()
                  << '\t' << s.regression_decrease() << '\n';
    }
    return failed ? 1 : 0;
}
