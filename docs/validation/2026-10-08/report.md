# P4 合成验证与性能报告

真实案例尚未验证：当前没有实测/独立计算基准和完整案例输入。不能据此宣称真实洪峰误差低于 20%。

合成验收：9/9 通过。

| DEM 规模 | 次数 | 流水线中位数(s) | 最慢(s) | 含启动最长(s) | 峰值工作集(MB) | 通过 |
|---|---:|---:|---:|---:|---:|---|
|128×128|2|5.32|5.51|10.67|211.64|True|
|256×256|2|7.00|7.30|11.88|212.94|True|
|512×512|2|19.86|20.72|23.74|218.61|True|
|1024×1024|2|135.39|155.77|163.13|391.46|True|

口径：独立子进程；流水线时间含 DEM 分析、水文计算、栅格/矢量/CSV/PNG/HTML 输出，不含导入依赖和创建输入 DEM；含启动时间同时记录。
峰值工作集为 Windows 报告的进程整个生命周期峰值，包含依赖与输入生成，不等同于机器剩余内存。
基准为规则倾斜合成地形，不能保证复杂真实地形同样耗时；单机少量重复不构成统计置信区间。
洪水参考使用指数/整数 Gamma 闭式解和非整数 PDF 数值积分；时间口径与产品一致，按区间起点离散降雨响应，不用于证明区间内均匀降雨连续解的精度。

详细值见 synthetic.json、performance.json、performance.csv 和 summary.json。

## 独立合成案例逐项结果

| 案例 | 类型 | 通过 |
|---|---|---|
|exponential_single_pulse|synthetic_hydrology|True|
|integer_gamma_with_losses|synthetic_hydrology|True|
|fractional_gamma_half_hour|synthetic_hydrology|True|
|zero_rainfall|synthetic_hydrology|True|
|rain_below_initial_loss|synthetic_hydrology|True|
|plane_32_30_30|synthetic_spatial|True|
|plane_32_10_20|synthetic_spatial|True|
|plane_64_30_30|synthetic_spatial|True|
|nested_storm_peak_monotonicity|synthetic_property|True|

上述案例输入与误差明细见 [synthetic.json](synthetic.json)，性能原始数据见 [performance.json](performance.json)。
产品源文件与测量时 Git 提交逐项核对，校验信息见 [provenance.json](provenance.json)。
真实案例状态始终单独保存为未验证，合成验收结果不替代实测精度。
