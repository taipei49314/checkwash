# greenwash 頂級化路線圖（落地版）

> **目標：** 把 greenwash 從「方法論已強的 pre-release」推到**品類級 / 企業可引用**的頂級水平。  
> **頂級定義：** 不是 0 bypass；是**邊界誠實、裝上即硬、便宜作弊極貴、知情作弊可量測、數字可複現**。  
> **版本錨點：** v0.1.15 現況  
> **日期：** 2026-08-11  
> **相關文件：**
>
> | 文件 | 用途 |
> |------|------|
> | [redteam-weaknesses.md](./redteam-weaknesses.md) | 第一輪可打穿的 10 洞 |
> | [redteam-residual-after-p0.md](./redteam-residual-after-p0.md) | 防住後的 L0–L2 殘餘 |
> | [../THREATMODEL.md](../THREATMODEL.md) | 公開 bypass 與接受極限 |
> | [../benchmarks/FAILURES.md](../benchmarks/FAILURES.md) | 未關閉失敗面 |
> | [../SPEC.md](../SPEC.md) | 凍結契約 |
> | [stability.md](./stability.md) | 對外穩定面 |
> | [integrations.md](./integrations.md) | 整合面 |

---

## 0. 一句話

> **頂級 greenwash = 誠實的邊界 + 裝上即 required + 便宜作弊極貴 + 知情作弊可量測且越刷越難 + 基準人人可複現。**

打穿你要嘛改 prod、要嘛動流程、要嘛留下人審髒指紋——**預設 agent 走不通**。

---

## 1. 什麼叫「頂級」（驗收標準）

### 1.1 對照表

| 維度 | 二流 | 頂級（本路線圖驗收） |
|------|------|----------------------|
| **承諾** | 「防 AI 作弊」口號 | 保證邊界寫死 + 公開失敗面 |
| **預設路徑** | 裝了但 optional | Required check；繞過要動 branch protection |
| **Recall（對抗）** | demo 過得了 | 固定 informed suite；逃脫 → fixture SLA |
| **Precision** | FP「大概還行」 | 多 rater、逐筆公開、version 可回歸 |
| **確定性 / 速度** | 大多時候對 | 跨 OS/Python byte-identical + 延遲 SLO |
| **覆蓋** | 一種 assert / 一種 CI | Python 深 + CI 一跳 + monorepo 政策或第二語言 |
| **整合** | README 片段 | Action / pre-commit / hook / SARIF / doctor |
| **對手模型** | 只防笨 agent | 防「讀源碼 + 迭代 check」的成本曲線 |
| **治理** | 作者感覺 | SPEC 凍結、DECISIONS、dogfood 真跑、release 門禁 |

### 1.2 永不承諾（寫進對外文案）

| ID | 極限 | 誰負責 |
|----|------|--------|
| #1 | 改 production 讓舊測試「誠實」通過 | 人審 / 規格 / 執行層 |
| #3 | 不跑 greenwash、卸 required check | Branch protection / 組織政策 |
| L0-C | 多 commit / 多 PR 洗白 | Merge 視窗掃描 / process |
| — | 形式化證明「無作弊」 | 超出品類 |

**核心保持：** 0 LLM · 0 runtime network · 決定性 · 可進 stop-hook。  
執行證明 / mutation = **可選衛星**，不污染預設路徑。

### 1.3 成功指標（門禁數字，可調但要有）

| 指標 | 方向性目標 | 量測來源 |
|------|------------|----------|
| 人類 corpus block rate | ~1–2% | 1800-commit sweep |
| 人類 FP（多數決） | ≤ ~1.2% 且逐筆可辯 | adjudication JSON |
| Decoy 對抗 recall | ≥ 95%（擴充後）或維持 12/12 | `benchmarks/decoy/` |
| Informed 固定集 | 逃脫必須是 #1 / 多 PR / 深 mock，且文件化 | release 任務集 |
| 引擎 error | 0（3.11–3.13） | CI |
| p95 延遲（中型 diff） | stop-hook 路徑 < 2s | `tests/gates/test_perf.py` |
| 外部採用 | N 個 repo 以 required check 跑 | 手動 / badge 統計 |
| 逃脫 SLA | informed 逃脫 → 下一個 minor 關閉或標 Open by design | THREATMODEL + fixture |

---

## 2. 現況盤點（v0.1.15）

### 2.1 已具頂級基因（保持）

- [x] 分析 **diff**，config / allowlist / contract 讀 **base** 側  
- [x] Strength lattice + 19 detectors + 可審核 gating  
- [x] 公開 THREATMODEL / FAILURES / DECISIONS  
- [x] 1800-commit 人類 corpus + 三 rater FP  
- [x] Decoy / probe / informed arms  
- [x] Dogfood（CI 對自己跑 action）  
- [x] 0 依賴、pyz、Action、pre-commit、hook  
- [x] Closed bypass 需 fixture pin（`test_threatmodel_pinned`）

### 2.2 與頂級的主要差距

| 差距 | 後果 |
|------|------|
| 部署預設偏「可選」 | 引擎強但門沒鎖 |
| 第二層 indirection（fixture / mock / 兩跳 / 間接 script） | 知情對手仍便宜 |
| Informed 未成 **release 門禁** | 回歸靠意志 |
| PR UX / SARIF / allow 治理 | 難進企業標準 |
| Monorepo / 非 Python opaque | 整大陸躺平或誤免死 |
| 產品敘事「保證 vs 成本」 | 期望錯位 → 覺得沒用 |

### 2.3 五根柱子

```
        ┌──────────── 信任（數字可複現）────────────┐
        │                                              │
  部署硬度 ── 引擎深度 ── 覆蓋面 ── 產品體驗 ── 生態
  (required)  (oracle+CI)  (lang/CI)  (裝/報/豁免)  (被依賴)
```

缺「部署硬度」→ 再強也是 side project。  
缺「信任數字」→ 只有故事。

---

## 3. 階段路線圖

### Phase T0 — 裝上就硬（優先最高）

**目標：** 新用戶 10 分鐘內達到「合併必須過 greenwash」。  
**預估：** 2–4 週專注度（視文件與腳本深度）。

| ID | 工作項 | 驗收 | 優先 |
|----|--------|------|------|
| T0.1 | README / integrations **首屏**：Required check 三步驟（含 branch protection） | 新用戶照做可鎖合併 | P0 |
| T0.2 | Action 範本：最小 `permissions`、`persist-credentials: false`、通過 zizmor 級檢查 | 範本可被安全 repo 合併 | P0 |
| T0.3 | `greenwash doctor`：偵測 range 建議、config 路徑、是否像 optional-only | CLI 輸出可行動建議 | P0 |
| T0.4 | （可選）`gh` / 文件腳本：提示如何設 required status name | 文件可複現 | P1 |
| T0.5 | 對外一句話釘死：**不 required = 不宣稱 CI 防禦** | launch / README 可見 | P0 |
| T0.6 | 偵測或文件化：greenwash **自身 job** 被刪 / `if: false` 的殘餘風險 | THREATMODEL 或 doctor 警告 | P1 |

**T0 完成定義（DoD）：**

- [ ] 文件路徑：clone → install → Action → required check 無歧義  
- [ ] `doctor` 在「只裝沒鎖」時會警告  
- [ ] CI 防禦宣稱與 required 綁定  

---

### Phase T1 — 知情對手變貴（引擎 P0/P1）

**目標：** informed arm 從「讀源碼就穿」→「多數要 mock / 改 prod / 多 PR」。  
**對應：** `redteam-weaknesses.md` P0–P1 + 殘餘 L1 高優。

| ID | 工作項 | 關閉 / 緩解 | 驗收 | 優先 |
|----|--------|-------------|------|------|
| T1.1 | IR：binding **定義式** 兩側 diff | #86a | pos/neg `.gwcase` + 舊 fixture 不破 | P0 |
| T1.2 | Fixture / parametrize **期望資料** 變更偵測 | L1 fixture 靜音 | 至少 conftest + 同檔 fixture + parametrize 欄 | P0 |
| T1.3 | Subject **有界 dataflow k=2** + 參數 wrap | #84 遷移 | 兩跳 hoist 有 finding；合法 rename 不炸 FP | P1 |
| T1.4 | Test 內 first-party `monkeypatch`/`patch`（可 disable） | L1 mock | 對齊 CONFTEST_PATCHES_PROD 哲學；stdlib stub 安靜 | P1 |
| T1.5 | Workflow → 呼叫的 script **再掃一層** | CI 間接卸責 | `ci_entry.sh`→`real_test.sh` 弱化可 high | P1 |
| T1.6 | Collection：路徑集合 diff +（粗）hook body remove vs mark | #81 族 / plugin | 追加 ignore 路徑有事件；`--runslow` 標記路徑 FP 可接受或分流 | P1 |
| T1.7 | **Informed suite 進 release gate** | 治理 | 固定 ≥6 題；逃脫必須 Open by design 或擋 | P0 |
| T1.8 | Imperative skip guard 語意 diff | #54 | 與 #59 同族；allowlist 遷移策略寫 DECISIONS | P1 |

**T1 DoD：**

- [ ] 每個 T1 項有 `.gwcase` 或 e2e pin  
- [ ] `tests/test_threatmodel_pinned.py` 對應列更新  
- [ ] Release checklist 含 informed suite  
- [ ] 人類 corpus 重跑：FP 不惡化超過約定閾值（建議 ΔFP ≤ 0.3pp 需書面）  

---

### Phase T2 — 企業可引用（產品化）

**目標：** 安全 / 平台團隊願意寫進 internal standard。

| ID | 工作項 | 驗收 | 優先 |
|----|--------|------|------|
| T2.1 | SARIF 輸出 | `greenwash check --format sarif` 可被 code scanning 吃 | P0 |
| T2.2 | PR 行級註解（Action 選配） | finding 掛在 path/line | P1 |
| T2.3 | Allow 工作流：理由 + 過期 + 建議 CODEOWNERS | `allow` CLI + 文件 | P0 |
| T2.4 | 穩定機器介面：findings schema / version 文件化 | stability.md 對齊 | P0 |
| T2.5 | 效能 SLO 寫進 CI gate | perf 失敗不可 silently skip | P1 |
| T2.6 | 供應鏈：Action 釘版、無寫權 token、release pyz 可複現 | RELEASING + CI | P1 |
| T2.7 | 診斷級 report：差哪個 de-escalator、建議下一步 | term 輸出可讀 | P2 |

**T2 DoD：**

- [ ] 企業 POC 清單（required + SARIF + allow 過期）可一頁走完  
- [ ] semver：breaking 只碰 SPEC 標註面  

---

### Phase T3 — 品類定義者（生態與邊界做絕）

**目標：** 提到 agent test-tampering 就想到 greenwash。

| ID | 工作項 | 驗收 | 優先 |
|----|--------|------|------|
| T3.1 | **二選一做絕：** JS/TS 最小 oracle **或** monorepo「非 Python 不給 diff-global opaque 免死」硬政策 | 文件 + 量測 | P0 |
| T3.2 | `greenwash bench` / 一鍵複現 sweep+decoy | 外部可複現 | P1 |
| T3.3 | 對標 harness 固定化（AgentLint / 同類） | `benchmarks/compare` 可重跑 | P2 |
| T3.4 | 外部 cheat 貢獻節奏（issue 模板已有 → 季度回顧） | FAILURES 有外部 credited 列 | P2 |
| T3.5 | **衛星（可選獨立套件）：** 執行陪跑 / mutation | 不進預設 core | P3 |
| T3.6 | 多 commit / PR 視窗掃描文件 + 可選 `sweep` 整合 | process 文件 | P2 |

**T3 DoD：**

- [ ] 第二前線（語言或 opaque 政策）有 corpus 數字  
- [ ] 基準成為他人可引用 baseline  

---

## 4. 引擎工作拆解（與紅隊對齊）

### 4.1 第一輪 10 洞 → 工程隊列

| 順位 | 項 | 來源 | 建議 Phase |
|------|-----|------|------------|
| P0 | Expected 綁定定義式 diff | #86a | T1 |
| P0 | Subject 一跳 + 參數 wrap；再 k=2 | #84 | T1 |
| P1 | Opaque E1 per-finding 或再收窄 | #2/#68 | T1（政策） |
| P1 | Imperative guard 語意 | #54 | T1 |
| P2 | Runner 檔名 / PS·bat / 一跳 script | #75–77 | T1.5 + T1 |
| P2 | collect_ignore 語意 / handlers | #81/#83 | T1.6 |
| P3 | unittest DERIVED、#86e 無 subject 替換 | #86b/#86e | T1 尾或 T2 |
| — | #1 改 prod、#3 不跑 | L0 | 只文件 + T0 部署 |

完整攻擊細節見 [redteam-weaknesses.md](./redteam-weaknesses.md)。

### 4.2 防住後殘餘 → 不幻想一次關完

| 層 | 策略 |
|----|------|
| **L0** | 文件 + required + 多窗口 process；**不**塞進 core 假保證 |
| **L1** | T1 主戰場（fixture、mock、兩跳、間接 CI、plugin） |
| **L2** | T1 尾 / T3：D6 helper 內聯、alignment 鬆、xfail、Hypothesis… |

見 [redteam-residual-after-p0.md](./redteam-residual-after-p0.md)。

### 4.3 每個引擎 PR 的強制 checklist

```markdown
- [ ] 同一 PR：detector 或 gating 變更 + pos/neg `.gwcase`
- [ ] 不改既有 fixture 期望（錯了開 issue）
- [ ] SPEC / THREATMODEL / DECISIONS 該動的才動（agent 只讀政策檔）
- [ ] 本地：`pytest` +（若動 CI 語意）相關 runner cases
- [ ] 若動 escalator：記錄對 1800 corpus 的預期影響或抽樣重跑
- [ ] Dogfood：本 PR 的 greenwash 結論可解釋
```

---

## 5. Release 門禁（頂級治理）

### 5.1 每個 minor / 標籤版必跑

| 門禁 | 命令 / 產物 | 失敗則 |
|------|-------------|--------|
| 單元 + cases | `pytest` | 不可發版 |
| Threatmodel pin | `tests/test_threatmodel_pinned.py` | 不可發版 |
| Zipapp | `tests/test_zipapp.py` | 不可發版 |
| Dogfood job | CI `dogfood` | 不可發版 |
| Perf gate | `tests/gates/test_perf.py` | 不可發版（或標 known） |
| Decoy 回歸 | 錄製 arm 或 replay fixture | recall 退步要 DECISIONS |
| **Informed 固定集**（T1.7 後） | 文件化任務列表 | 逃脫未標 Open → 不可發版 |
| 人類 sweep 抽樣 | 至少一 repo 300 commits 或全量週期跑 | FP 暴增要擋 |

### 5.2 逃脫 SLA

```
發現逃脫（內部 arm 或外部 issue）
  → 48h 內：THREATMODEL 列 + 最小 repro
  → 下一個 minor：fixture pin 關閉，或標 Open / Open by design + 理由
  → 禁止：Closed 無 pin（已有測試）
```

### 5.3 版本政策（摘要）

| 變更 | 版本 |
|------|------|
| 新 detector、收窄逃脫、文件 | patch / minor |
| Strength 數值、對齊參數、findings schema 破壞 | SPEC bump + minor/major 依 stability.md |
| 預設 `fail_on`、角色 glob 破壞性變更 | 明確 changelog + 版本 |

---

## 6. 產品與敘事（避免「沒用」錯覺）

### 6.1 對外標準句

**做什麼：**  
提高 coding agent（與人）透過**動驗證層**讓 CI 變綠的成本；決定性、本地、可進 stop-hook。

**不做什么：**  
不保證無作弊；不驗證 prod 語意正確；不替代 required CI 與人審。

**CI 宣稱：**  
在 **greenwash 為 required check** 且測試命令落在已建模表面時，對「把測試命令寫廢」類變更可 block。  
不 required → 不宣稱 CI 防禦。

### 6.2 文件地圖（建議首屏連結）

```
README
  ├─ 60 秒上手 + required 三步驟
  ├─ 量測摘要 → benchmarks/
  ├─ 已知失敗 → FAILURES.md（誠實）
  ├─ 整合 → docs/integrations.md
  ├─ 頂級路線圖 → docs/ROADMAP-top-tier.md（本檔）
  └─ 紅隊 → docs/redteam-*.md
```

### 6.3 定位對照（給質疑「總是有洞」）

| 錯誤標準 | 正確標準 |
|----------|----------|
| 永遠繞不過 | 默認不划算繞；繞完留下人審指紋 |
| 單一工具封頂 | Tripwire + required CI + 人審 |
| 0 Open bypass | Open 公開、成本可解釋 |

---

## 7. 建議執行順序（資源有限時）

```
1. T0 部署硬度          ← 沒有則全是學術
2. T1.7 informed 門禁   ← 沒有則引擎空轉
3. T1.1 + T1.2          ← 最大靜音洞
4. T1.5 CI 一跳 script  ← CI 宣稱站得住
5. T1.3 / T1.4 / T1.6   ← 知情下一刀
6. T2 SARIF + allow     ← 企業可引用
7. T3 第二前線          ← 品類
```

**不要先做：** 堆 rule ID、LLM 層、大改網站、同時十種語言。

---

## 8. GitHub Issues / Milestones（已開立 2026-08-11）

| 資源 | URL |
|------|-----|
| **Epic tracker** | https://github.com/taipei49314/greenwash/issues/35 |
| Issues 列表 | https://github.com/taipei49314/greenwash/issues |
| Milestones | https://github.com/taipei49314/greenwash/milestones |

Labels：`roadmap` · `phase-t0`…`phase-t3` · `engineering` · `P0`–`P3`

### Milestone 1 — `T0-required-by-default`

| ID | Issue | 標題摘要 |
|----|-------|----------|
| T0.1 | [#2](https://github.com/taipei49314/greenwash/issues/2) | Required check 三步驟文件 |
| T0.2 | [#3](https://github.com/taipei49314/greenwash/issues/3) | Action 安全範本 |
| T0.3 | [#4](https://github.com/taipei49314/greenwash/issues/4) | `greenwash doctor` |
| T0.4 | [#5](https://github.com/taipei49314/greenwash/issues/5) | gh 設 required（可選） |
| T0.5 | [#6](https://github.com/taipei49314/greenwash/issues/6) | CI 宣稱綁 required |
| T0.6 | [#7](https://github.com/taipei49314/greenwash/issues/7) | self-job 被卸風險 |

### Milestone 2 — `T1-informed-cost`

| ID | Issue | 標題摘要 |
|----|-------|----------|
| T1.1 | [#8](https://github.com/taipei49314/greenwash/issues/8) | binding 定義式 diff（#86a） |
| T1.2 | [#9](https://github.com/taipei49314/greenwash/issues/9) | fixture / parametrize 期望 |
| T1.3 | [#10](https://github.com/taipei49314/greenwash/issues/10) | dataflow k=2 + 參數 wrap |
| T1.4 | [#11](https://github.com/taipei49314/greenwash/issues/11) | test-local first-party patch |
| T1.5 | [#12](https://github.com/taipei49314/greenwash/issues/12) | CI workflow→script 一跳 |
| T1.6 | [#13](https://github.com/taipei49314/greenwash/issues/13) | collection path-set / hooks |
| T1.7 | [#14](https://github.com/taipei49314/greenwash/issues/14) | informed suite release gate |
| T1.8 | [#15](https://github.com/taipei49314/greenwash/issues/15) | imperative skip guard（#54） |

### Milestone 3 — `T2-enterprise-surface`

| ID | Issue | 標題摘要 |
|----|-------|----------|
| T2.1 | [#16](https://github.com/taipei49314/greenwash/issues/16) | SARIF |
| T2.2 | [#17](https://github.com/taipei49314/greenwash/issues/17) | PR 行註解（可選） |
| T2.3 | [#18](https://github.com/taipei49314/greenwash/issues/18) | allow 工作流 / CODEOWNERS |
| T2.4 | [#19](https://github.com/taipei49314/greenwash/issues/19) | findings schema 穩定契約 |
| T2.5 | [#20](https://github.com/taipei49314/greenwash/issues/20) | perf SLO CI gate |
| T2.6 | [#21](https://github.com/taipei49314/greenwash/issues/21) | 供應鏈 / pyz |
| T2.7 | [#22](https://github.com/taipei49314/greenwash/issues/22) | 診斷級 report |

### Milestone 4 — `T3-category-defining`

| ID | Issue | 標題摘要 |
|----|-------|----------|
| T3.1 | [#23](https://github.com/taipei49314/greenwash/issues/23) | JS/TS 或 opaque 硬政策 |
| T3.2 | [#24](https://github.com/taipei49314/greenwash/issues/24) | `greenwash bench` |
| T3.3 | [#25](https://github.com/taipei49314/greenwash/issues/25) | compare harness |
| T3.4 | [#26](https://github.com/taipei49314/greenwash/issues/26) | 外部 cheat 節奏 |
| T3.5 | [#27](https://github.com/taipei49314/greenwash/issues/27) | 執行衛星（非 core） |
| T3.6 | [#28](https://github.com/taipei49314/greenwash/issues/28) | 多 PR 洗白 process 文件 |

### Milestone 5 — `Engineering-hygiene`（靜態 review）

| ID | Issue | 標題摘要 |
|----|-------|----------|
| E1 | [#29](https://github.com/taipei49314/greenwash/issues/29) | `ir/astutil` 抽共用 |
| E2 | [#30](https://github.com/taipei49314/greenwash/issues/30) | Finding.shape |
| E3 | [#31](https://github.com/taipei49314/greenwash/issues/31) | REGISTRY ⊆ RULE_ORDER 測試 |
| E4 | [#32](https://github.com/taipei49314/greenwash/issues/32) | unittest names / bindings |
| E5 | [#33](https://github.com/taipei49314/greenwash/issues/33) | 拆 build_ir / apply_gates |
| E6 | [#34](https://github.com/taipei49314/greenwash/issues/34) | weakened subject 結構比較 |

### 下週最小包（附錄 B → issues）

| 做什麼 | Issue |
|--------|-------|
| Required 文件 + 宣稱 | [#2](https://github.com/taipei49314/greenwash/issues/2) · [#6](https://github.com/taipei49314/greenwash/issues/6) |
| Informed gate 骨架 | [#14](https://github.com/taipei49314/greenwash/issues/14) |
| #86a 設計 + 紅燈 fixture | [#8](https://github.com/taipei49314/greenwash/issues/8) |
| （可選）工程小勝 | [#29](https://github.com/taipei49314/greenwash/issues/29) · [#30](https://github.com/taipei49314/greenwash/issues/30) |

> **注意：** `docs/ROADMAP-top-tier.md` 與紅隊 MD 目前可能僅在本機 clone；commit/push 後 Epic #35 內的 blob 連結才會在 GitHub 上可點。

---

## 9. 架構紅線（走歪就不是 greenwash）

| 做 | 不做 |
|----|------|
| 核心 0 LLM / 0 network / 決定性 | 預設路徑塞 LLM judge |
| 逃脫 → fixture → 文件 | 默默調 severity「感覺好」 |
| 新 de-escalator 先紅隊 | 為 FP 開洞重演 bypass #4 |
| 執行層當衛星套件 | 為「保證」毁掉 sub-second hook |
| 公開 FAILURES | 行銷刪失敗面 |
| Agent 可改 detector + cases | Agent 改 SPEC / gating 政策 / strength 數值 |

見 root `AGENTS.md`。

---

## 10. 檢查清單總表（可印出追蹤）

### T0

- [ ] T0.1 Required 三步驟文件 → #2  
- [ ] T0.2 Action 安全範本 → #3  
- [ ] T0.3 `doctor` → #4  
- [ ] T0.5 宣稱與 required 綁定 → #6  
- [ ] T0.4 / T0.6 可選項 → #5 · #7  

### T1

- [ ] T1.1 Binding diff → #8  
- [ ] T1.2 Fixture / parametrize → #9  
- [ ] T1.3 Dataflow k=2 → #10  
- [x] T1.4 Test-local patch → #11 (v0.1.25, `TEST_PATCHES_SUBJECT`)  
- [ ] T1.5 CI script one-hop → #12  
- [ ] T1.6 Collection 語意 → #13  
- [ ] T1.7 Informed release gate → #14  
- [ ] T1.8 Guard #54 → #15  

### T2

- [ ] T2.1 SARIF → #16  
- [ ] T2.2 PR 註解（選） → #17  
- [ ] T2.3 Allow 工作流 → #18  
- [ ] T2.4 Schema 穩定文件 → #19  
- [ ] T2.5 Perf SLO → #20  
- [ ] T2.6 供應鏈 → #21  
- [ ] T2.7 診斷 report → #22  

### T3

- [ ] T3.1 語言或 opaque 政策 → #23  
- [ ] T3.2 bench 一鍵 → #24  
- [ ] T3.3 對標固定化 → #25  
- [ ] T3.4 外部 cheat 節奏 → #26  
- [ ] T3.5 衛星執行層（可選） → #27  
- [ ] T3.6 多窗口 process → #28  

### Engineering

- [ ] E1 astutil → #29  
- [ ] E2 Finding.shape → #30  
- [ ] E3 REGISTRY/ORDER → #31  
- [ ] E4 unittest names → #32  
- [ ] E5 split modules → #33  
- [ ] E6 structural subject → #34  

### 常駐

- [ ] 每 release：pytest + pin + zipapp + dogfood  
- [ ] 逃脫 SLA 執行中  
- [ ] corpus / FP 週期重跑  
- [ ] DECISIONS 對大 trade 有記錄  

---

## 11. 結語

greenwash 已經具備頂級專案少見的 **誠實量測與對抗紀律**。  
落地頂級差的不是「再寫一篇理念」，而是：

1. **T0** 讓世界預設跑你、且合不了碼就繞不開  
2. **T1** 讓知情對手的下一刀變貴，並用 informed **門禁**鎖住  
3. **T2** 讓企業叫得動（SARIF、allow、穩定契約）  
4. **T3** 做絕第二前線，成為品類 baseline  

本文件即執行背板：按 Milestone 開 issue、按 DoD 勾選、按紅線不走歪。

---

## 附錄 A — 與紅隊文件的索引

| 主題 | 文件 |
|------|------|
| 現況 10 洞與攻擊配方 | [redteam-weaknesses.md](./redteam-weaknesses.md) |
| 防住後 L0–L2 | [redteam-residual-after-p0.md](./redteam-residual-after-p0.md) |
| CI 能防什麼 | 見紅隊 #6/#75–77 + 本檔 T0、T1.5 |
| 公開 bypass 權威表 | [../THREATMODEL.md](../THREATMODEL.md) |
| 未關閉與 FP | [../benchmarks/FAILURES.md](../benchmarks/FAILURES.md) |

## 附錄 B — 最小「下週就做」包

若只能做一週：

1. **T0.1 + T0.5**（文件：required + 宣稱）  
2. **T1.7** 骨架（3 題 informed 手動進 CI，即使未全自動）  
3. **T1.1** 設計稿 + 最小 `#86a` pos fixture 紅燈（TDD）  

一週結束應有：敘事不說滿、門開始鎖、最大靜音洞進工程佇列。
