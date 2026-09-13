#include "faithful.h"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#ifdef _WIN32
#include <windows.h>
#include <psapi.h>
#endif
using namespace trader::faithful;
using Clock=std::chrono::steady_clock;
double ms(Clock::time_point a,Clock::time_point b){return std::chrono::duration<double,std::milli>(b-a).count();}
int main(int argc,char** argv){try{
 if(argc!=7)throw std::invalid_argument("usage: trader_faithful case k ell eg|single|batch B trace");
 const std::string folder=argv[1],mode=argv[4];const auto k=std::stoul(argv[2]),ell=std::stoul(argv[3]),batch=std::stoul(argv[5]);
 if(!ell||!batch||(mode!="eg"&&mode!="single"&&mode!="batch")||((mode=="single"||mode=="eg")&&batch!=1))throw std::invalid_argument("invalid mode/ell/B");
 auto start=Clock::now();DirectedWeightedGraph graph;std::ifstream gf(folder+"/graph.txt");if(!gf)throw std::runtime_error("graph file");
 VertexId u,v;double w;while(gf>>u>>v>>w)graph.set_edge(u,v,w);if(!gf.eof())throw std::runtime_error("graph parse");
 std::vector<std::unique_ptr<Engine>> engines;std::vector<std::unique_ptr<Grouped>> groups;
 for(std::size_t i=0;i<ell;++i){std::string file=i?"colors_"+std::to_string(i)+".txt":"colors.txt";std::ifstream cf(folder+"/"+file);if(!cf)throw std::runtime_error("color file");
   ColorMap colors;Color color;VertexId vertex=0;while(cf>>color)colors[vertex++]=color;if(!cf.eof()||colors.empty())throw std::runtime_error("color parse");
   if(mode=="eg")groups.push_back(std::make_unique<Grouped>(graph,colors,k));else engines.push_back(std::make_unique<Engine>(graph,colors,k));
 }
 double init=ms(start,Clock::now());std::ofstream trace(argv[6]);if(!trace)throw std::runtime_error("trace file");
 trace<<std::setprecision(17)<<"row\tweight\tpath\tcoloring\n";
 auto query=[&]{CycleAnswer best;std::size_t coloring=0;for(std::size_t i=0;i<ell;++i){auto a=mode=="eg"?groups[i]->answer():engines[i]->best();if(a.exists&&(!best.exists||a.weight<best.weight)){best=std::move(a);coloring=i;}}return std::make_pair(best,coloring);};
 auto emit=[&](std::size_t row,const std::pair<CycleAnswer,std::size_t>& answer){auto& a=answer.first;trace<<row<<'\t';if(a.exists)trace<<a.weight;else trace<<"none";trace<<'\t';for(std::size_t i=0;i<a.cycle.size();++i)trace<<(i?" ":"")<<a.cycle[i];trace<<'\t'<<answer.second<<'\n';};
 emit(0,query());std::cerr<<"INITIALIZED init_ms="<<init<<" mode="<<mode<<" ell="<<ell<<'\n';
 std::ifstream input(folder+"/updates.txt");if(!input)throw std::runtime_error("updates file");
 std::size_t rows=0,queries=0;std::vector<EdgeUpdate> pending;double core=0;start=Clock::now();
 auto flush=[&]{auto began=Clock::now();for(auto& engine:engines)engine->apply_batch(pending);auto a=query();core+=ms(began,Clock::now());emit(rows,a);++queries;pending.clear();};
 std::string line;while(std::getline(input,line)){
   ++rows;std::istringstream in(line);std::string value;if(!(in>>u>>v>>value))throw std::runtime_error("update parse");
   EdgeUpdate update{u,v,value=="N"||value=="D"?0:std::stod(value),value=="D","",rows};
   if(mode=="eg"){auto began=Clock::now();if(value!="N")for(auto& group:groups)group->update(update);auto a=query();core+=ms(began,Clock::now());emit(rows,a);++queries;}
   else {if(value!="N")pending.push_back(update);if(rows%batch==0)flush();}
 }
 if(mode=="eg"){auto began=Clock::now();for(auto& group:groups)group->flush();core+=ms(began,Clock::now());}
 else if(rows%batch)flush();
 trace.flush();double online=ms(start,Clock::now());double peak=-1;
#ifdef _WIN32
 PROCESS_MEMORY_COUNTERS counters{};if(!GetProcessMemoryInfo(GetCurrentProcess(),&counters,sizeof(counters)))throw std::runtime_error("peak memory read");peak=double(counters.PeakWorkingSetSize)/1048576;
#endif
 Metrics total;std::size_t states=0,candidates=0,links=0;
 for(std::size_t i=0;i<ell;++i){const Engine& e=mode=="eg"?groups[i]->engine():*engines[i];auto m=e.metrics;
   total.popped+=m.popped;total.repaired+=m.repaired;total.candidate_refreshes+=m.candidate_refreshes;total.maintained+=m.maintained;total.deferred+=m.deferred;
   total.changed_states+=m.changed_states;total.unchanged_repairs+=m.unchanged_repairs;
   total.schedule_ms+=m.schedule_ms;total.repair_ms+=m.repair_ms;total.propagation_ms+=m.propagation_ms;total.candidate_ms+=m.candidate_ms;total.classification_ms+=m.classification_ms;
   states+=e.states().size();candidates+=e.ranking().size();links+=e.witness_links();
 }
 std::cout<<std::setprecision(17)<<"{\"method\":\"TRADER-paper-reconstruction-terminal-v3\",\"mode\":\""<<mode<<"\",\"k\":"<<k<<",\"ell\":"<<ell<<",\"batch\":"<<batch
 <<",\"rows\":"<<rows<<",\"queries\":"<<queries<<",\"init_ms\":"<<init<<",\"online_ms\":"<<online<<",\"core_ms\":"<<core<<",\"peak_rss_mib\":"<<peak
 <<",\"states\":"<<states<<",\"candidates\":"<<candidates<<",\"witness_links\":"<<links<<",\"queue_pops\":"<<total.popped<<",\"repaired_states\":"<<total.repaired
 <<",\"candidate_refreshes\":"<<total.candidate_refreshes<<",\"maintenance_batches\":"<<total.maintained<<",\"deferred\":"<<total.deferred
 <<",\"state_finalizations\":"<<total.popped<<",\"changed_states\":"<<total.changed_states<<",\"unchanged_repairs\":"<<total.unchanged_repairs
#ifdef TRADER_PROFILE
 <<",\"profile\":true,\"schedule_ms\":"<<total.schedule_ms<<",\"repair_ms\":"<<total.repair_ms<<",\"propagation_ms\":"<<total.propagation_ms<<",\"candidate_ms\":"<<total.candidate_ms<<",\"classification_ms\":"<<total.classification_ms
#else
 <<",\"profile\":false"
#endif
 <<"}\n";return 0;
}catch(const std::exception& ex){std::cerr<<ex.what()<<'\n';return 1;}}
