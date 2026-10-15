# die 双峰分析（R4 A 组 cf0.25 cards8 copy300 case JSON，2026-10-15 蓝区）

> 证据等级：**实测值**（绿区 R4 交付 da22c6c，pingpong.md §R4 交付节
> A/frac JSON 全文）；机制归因标注**推测**。

## 实测数据（per-device phases，数组顺序即 die 0..7）

| die | launch_to_gather_done_us | 相对慢档 |
| --- | ---: | --- |
| 0 | 284.63 | 1.00x |
| 1 | 273.53 | 1.00x |
| 2 | 280.71 | 1.00x |
| 3 | **167.07** | **快 1.70x** |
| 4 | 285.82 | 1.00x |
| 5 | 284.12 | 1.00x |
| 6 | 275.09 | 1.00x |
| 7 | **155.39** | **快 1.83x** |

- 慢档六 die 均值 280.64µs，快档两 die 均值 161.23µs，比值 **1.74x**。
- 折叠均值 254.0µs、max 302.4µs——max/mean 长尾与双峰互洽。
- 同一 case 内 kernel_event_us（die0 = 284.16）与 gather（284.63）基本
  相等：慢档 die 上 kernel（75% 份额）与 CPU gather（25% 份额）恰好
  平衡；快档 die 上 gather 提前 ~110µs 完成，kernel 成为唯一长杆。
- die0 的迭代级 min=175.11µs（p50=296.5）：慢档 die 偶尔也能跑到快档
  水平——说明不是 die 本身慢，而是**访存路径**快慢两态。

## 机制归因（推测，与全部事实一致）

DRAM 镜像池的物理页由 first-touch 分配：池创建线程落在哪个 NUMA 节点，
整池页就在哪个节点。8 个 worker 进程（每 die 一个）里，与池同节点的
worker 本地访存快，跨节点的走互连慢。R4 未设 NUMA 绑定（四环境变量
无匹配在案），worker 落点由 OS 调度。

**待解释的配对形态**：快档是 die3+die7，不是整 socket 的 4+4 配对
（如 0-3 / 4-7）。若整机为 2 socket × 4 die，单节点池应给 4 个快 die，
实测只有 2 个——与简单单节点模型不符。可能形态（均推测）：4 NUMA
节点（2 die/节点）下池页 striped 落两节点、或调度器只把 2 个 worker
放进了池节点。准确拓扑待 R6 分支 B 的 `numactl -H` 输出 + 绑定扫描
裁决（派单已含该命令）。

## 对项目判断的三个影响

1. **cf0.25 凹陷的一个解释**：frac 曲线非单调（cf0.25 低于 cf0.1/0.4）
   部分来自 die 落点的 run 间差异——worker 调度落点每次 run 不同，
   快慢 die 数量浮动直接改变折叠值。**run 级噪声的一个具体机制**，
   支持 R5 高重复确认跑的设计。
2. **NUMA 可能是比 hybrid 更大的优化点**：若池按节点 interleave 或
   worker 绑核到池节点，全部 die 的 gather 有望从 ~281µs 压到 ~161µs
   （-43%）——对 cpu/hybrid 路径的收益远超 R4 S2 的 +4.5% 边际。
   **R6 分支 B（NUMA 扫描）优先级应上调**，即使 R5 强阳性也值得跑。
3. **生产形态设计稿补充**：DRAM 池镜像的 NUMA 放置策略（interleave
   / 按 die 亲和分区）应写进正式配置候选，与 pretouch 并列。

## 待验证（派单队列）

- R6+：`--numa-nodes` 扫描（drafts/R6_variants.md 分支 B）——若绑定后
  全 die gather 趋近 ~161µs，双峰归因实锤。
- 备选实验：池镜像改为 numa interleave 分配（改 worker 分配调用），
  复测 cf0.1/0.25 cards8 copy300。
