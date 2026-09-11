#include "delta_engine.hpp"
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>

// Internal line protocol: INIT n k edge_count, colors, edge rows; B count, rows.
// Every complete batch is applied atomically. EOF closes the session.
std::string line() {
    std::string value;
    if (!std::getline(std::cin, value)) throw std::runtime_error("incomplete input");
    return value;
}
void end(std::istringstream& in) {
    in >> std::ws;
    if (!in.eof()) throw std::runtime_error("unexpected trailing input");
}
std::vector<delta::Update> rows(size_t count, int n, bool initial) {
    std::vector<delta::Update> result;
    for (size_t i=0; i<count; ++i) {
        std::istringstream in(line()); int u,v; std::string value;
        if (!(in>>u>>v>>value)) throw std::runtime_error("invalid edge row");
        end(in);
        char op=value=="D"?'D':value=="N"?'N':'S';
        double w=0;
        if (op=='S') {
            size_t consumed=0; w=std::stod(value,&consumed);
            if (consumed!=value.size() || !std::isfinite(w) || std::abs(w)>1e100)
                throw std::runtime_error("weight outside supported finite range");
        }
        if (u<0 || v<0 || u>=n || v>=n || (op!='N' && u==v) || (initial && op!='S'))
            throw std::runtime_error("invalid edge endpoints or operation");
        result.push_back({u,v,w,op});
    }
    return result;
}
void emit(delta::DeltaEngine& engine, size_t row) {
    auto answer=engine.query();
    std::cout<<std::setprecision(17)<<"{\"row\":"<<row<<",\"weight\":";
    if (std::isfinite(answer.first)) std::cout<<answer.first; else std::cout<<"null";
    std::cout<<",\"path\":[";
    for(size_t i=0;i<answer.second.size();++i)std::cout<<(i?",":"")<<answer.second[i];
    std::cout<<"],\"states\":"<<engine.states.size()<<",\"arcs\":"<<engine.arcs.size()
             <<",\"recomputed\":"<<engine.recomputed<<",\"update_ms\":"<<engine.update_ms
             <<",\"query_ms\":"<<engine.query_ms<<"}"<<std::endl;
}
int main() {
    try {
        std::istringstream header(line()); std::string command; int n,k; size_t count;
        if (!(header>>command>>n>>k>>count) || command!="INIT" || n<1 || k<2 || k>10)
            throw std::runtime_error("invalid INIT parameters");
        end(header);
        std::vector<int> colors(n); std::istringstream input(line());
        for(auto& c:colors)if(!(input>>c)||c<0||c>=k)throw std::runtime_error("invalid colors");
        end(input);
        delta::DeltaEngine engine(colors,k);
        engine.initialize(rows(count,n,true)); emit(engine,0);
        size_t row=0; std::string next;
        while(std::getline(std::cin,next)) {
            std::istringstream in(next);
            if(!(in>>command>>count)||command!="B")throw std::runtime_error("invalid batch");
            end(in);
            auto updates=rows(count,n,false);
            engine.apply(updates,0,updates.size()); row+=count; emit(engine,row);
        }
        return 0;
    } catch(const std::exception& e) {
        std::cerr<<"DELTA: "<<e.what()<<'\n'; return 1;
    }
}
