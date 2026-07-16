# Complete Traceability Case

This case is selected deterministically as the complete row with the highest median-gas estimated net profit. Selection does not imply that the transaction was executable or realized at the time.

## Observation coordinate

- Chain: Ethereum mainnet (`chain_id=1`)
- Block: `25545598`
- Block hash: `0x1530c648adf14f34b2494ee322756a5b99798202045fbff1250a1ea41ee3aff8`
- Parent hash: `0x7a5d03418e73745317b0bfc19e68b2324b0fc95d265064a625ef9f650ea2bb61`
- Timestamp: `2026-07-16T13:42:35Z`
- Route: `WETH_USDT_USDC_WETH`
- Input: `0.01 WETH` (`10000000000000000` raw units)

## State provenance and three-hop calculation

Each state is the selected block's end-of-block reserve state. A carried state points to the latest preceding `Sync` event.

### Hop 1: WETH → USDT

- Pair: `0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852`
- State quality at block 25545598: `carried_forward`
- Last state-changing Sync source: block `25545586`, tx `0xadc837259586730646b8bb460577138c1dfd9e7f42355e761385af57e030ccf9`, log `408`
- Pair raw reserves: reserve0=`3917977234052526498135`, reserve1=`7384577612861`
- Oriented reserves: reserve_in=`3917977234052526498135`, reserve_out=`7384577612861`
- Integer CFMM output raw: `18791342`

### Hop 2: USDT → USDC

- Pair: `0x3041cbd36888becc7bbcbc0045e3b1f144466f5f`
- State quality at block 25545598: `carried_forward`
- Last state-changing Sync source: block `25545276`, tx `0x70c314ed26835b70df0491d6082c086cb5590a8fe6d44aefe46351ae6f91dfb9`, log `650`
- Pair raw reserves: reserve0=`1667847355905`, reserve1=`1665681492358`
- Oriented reserves: reserve_in=`1665681492358`, reserve_out=`1667847355905`
- Integer CFMM output raw: `18759117`

### Hop 3: USDC → WETH

- Pair: `0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc`
- State quality at block 25545598: `carried_forward`
- Last state-changing Sync source: block `25545585`, tx `0x35ee9c15b6110f76627c3af8f78fab433765681b5985c6228b167bb334fe73bb`, log `1256`
- Pair raw reserves: reserve0=`8793917564588`, reserve1=`4672501448912030034919`
- Oriented reserves: reserve_in=`8793917564588`, reserve_out=`4672501448912030034919`
- Integer CFMM output raw: `9937420820572355`

The contract-equivalent calculation at every hop is:

```text
amount_in_with_fee = amount_in × 997
amount_out = reserve_out × amount_in_with_fee
             ÷ (reserve_in × 1000 + amount_in_with_fee)
```

Integer floor division is used. The 0.3% fee is therefore already present in each hop output and is not subtracted again.

## Price impact and gross profit

- Final output: `0.009937420820572355 WETH` (`9937420820572355` raw units)
- Marginal no-curve-movement gross profit: `-0.000062420380522178 WETH`
- Estimated price-impact cost: `0.000000158798905467 WETH`
- Gross profit after CFMM fees and price impact: `-0.000062579179427645 WETH`

## Receipt sample and gas proxy

- Successful sampled receipts: `50`
- P25 / P50 / P75 gas-unit proxy: `162537` / `207350` / `421959`
- Representative sampled receipt nearest P50: `0x8d5d9b381a9f376eb3babbdb496b1aaf5667917ef2fc0ca082e25757fa86ee4b`
- Representative receipt gas used: `207480`
- Block-specific effective gas-price proxy: `845677345` wei (`0.845677345 gwei`)
- Median-scenario gas cost: `0.000175351197485750 WETH`

Receipt `gas_used` is a proxy for scenario construction. It is not claimed to equal the gas of a standardized three-hop arbitrage contract.

## Estimated net result

```text
estimated_net_profit = gross_profit_weth - gas_cost_weth
                     = -0.000062579179427645 - 0.000175351197485750
                     = -0.000237930376913395 WETH
```

- Profitable after median gas: `false`
- Data status: `complete`
