# Local Data Only

Do not commit author-provided or transformed UNI1--UNI6 files here.

Set the environment variable `TRADER_UNI_DATA_DIR` to the local
`processed_graph_data_new` directory. Benchmark scripts must verify file hashes
against `../metadata/trader_uni1_uni6_files.csv` before reading the data.

Generated CSR snapshots, caches, and benchmark outputs also remain local and
must be reproducible from the original source plus committed scripts.
