# experiments

对照组的输入与产物。**数字不是手写的**，全部由脚本生成。

| 文件 | 内容 |
|---|---|
| `gtm177_formula_qc.csv` | GTM177 单本书的一次完整复核结果（222 块），可直接当输入复跑 |
| `labels.csv` | 人工标签：`page,block,truth`，truth ∈ {ok, wrong}（当前 7 块，全部来自逐字核对） |
| `results.md` | 脚本生成的两份报告：四本书规模 + GTM177 带标签的检出 |

## 复现

```
python -m pmocr.experiment --csv experiments/gtm177_formula_qc.csv \
    --labels experiments/labels.csv --md out.md
```

不给 `--labels` 就只出规模与人工成本，`--sweep 0.3:0.95:0.05` 控制阈值扫描范围。

## 标签规则

1. **一条标签对应单本书**。标签只写 `page` 与 `block`，不带书名；把多本书的 CSV 合并后再喂标签，
   同页名会撞车。脚本检测到一条标签命中多行会直接报错，不会悄悄算错。
2. `page` / `block` 必须和 `pages_json` 里的页名、块序号一致（块序号从 1 起，只数公式块）。
3. `truth` 只能 `ok` 或 `wrong`，来自对着原图的判读，不来自模型自评。
4. 判读标准：LaTeX 渲染出来与原图在**符号、上下标、系数、编号**上一致即 `ok`；
   原书印刷错误不算识别错误，但要记备注。

## 补标签的建议

随机抽 150 块（OK 100 / CHECK 30 / 未打分 20），双人判读、冲突仲裁。
150 块可把召回估到约 ±20 个百分点；要 ±10 个百分点约需 300 块。
