# greenwash 紅隊報告 II：前 10 防住之後，還能打穿什麼？

> **對象：** [taipei49314/greenwash](https://github.com/taipei49314/greenwash) v0.1.15  
> **前提：** 假設 `docs/redteam-weaknesses.md` 所列 10 個弱點的防禦都已重新設計並落地（P0/P1 完成）  
> **問題：** 還有沒有能打穿的路徑？  
> **短答：** 有。剩餘是方法論極限、第二層語意洞、以及部署 / 多提交洗白。  
> **日期：** 2026-08-11  
> **姊妹文件：** [redteam-weaknesses.md](./redteam-weaknesses.md)（第一輪 10 洞）

---

## 前提：什麼叫「前 10 都防住了」

假定至少完成：

| 輪次 | 項目 |
|------|------|
| P0 | #86a expected 綁定 diff；#84 一跳 dataflow / 參數 wrap |
| P1 | Opaque E1 收窄或 per-finding；#54 imperative guard 語意；runner 枚舉；#81/#83 collect_ignore |
| P2+ | custom helper 有界展開；unittest DERIVED；#86e 等 |

在此前提下，攻擊者**不能再**靠：

- 無關 opaque 檔壓整 diff E1（舊形）  
- 單行 `expected = ...` 改綁定且 assertion 行不動（若只追 unit 內 Name）  
- 單行 subject wrap / 上一行 hoist（一跳）  
- `if True: pytest.skip()` 改 guard 字面  
- 簡單 Justfile / collect_ignore append 舊形  

**仍能**靠本文 L0–L2。

---

## 三層剩餘攻擊面

```
┌─────────────────────────────────────────────┐
│  L0 永遠打得穿（工具設計邊界）                 │  ← 補 detector 無解
├─────────────────────────────────────────────┤
│  L1 前 10 關了之後的「第二招」                 │  ← 同族遷移 / 加一層 indirection
├─────────────────────────────────────────────┤
│  L2 更深 / 第一輪未當主角的洞                  │  ← 下一輪紅隊主戰場
└─────────────────────────────────────────────┘
```

---

## L0 — 永遠打得穿（不靠前 10 個洞）

這些路徑**不依賴**第一輪任一 bypass；P0–P2 全關上也不消失。

| # | 攻擊 | 為何無解 |
|---|------|----------|
| **A** | **改 production 讓舊 assert 變真** | Diff 層與「真修 bug」不可區分（THREATMODEL #1） |
| **B** | **不跑 greenwash** | 工具不在執行路徑上（#3）；必須 CI required check |
| **C** | **多提交 / 多 PR 洗白** | Commit1 加死碼、假 helper、 innocuous fixture；Commit2 只「修」期望——每步單獨看都像合法 |
| **D** | **語意等價改寫** | 例：`assert f(x)==1` → `assert not (f(x)!=1)`——格子同 strength、語意同；再深需要等價證明 / 執行 |
| **E** | **測試本來就弱** | 工具管「變弱」，不管「任務一開始就沒有 oracle」 |

### 實務含義

- informed adversary 最便宜的一刀**永遠是 A**（改 prod）。  
- 組織若只靠 stop-hook、沒有 required CI check → **B 必勝**。  
- 只掃「最後一個 commit」或單一 PR → **C 系統性漏**。

---

## L1 — 前 10 關了之後，同族「下一刀」

### 1. Dataflow 只修一跳 → 兩跳仍洗

修 #84「上一行 wrap」後：

```python
tmp = encode(s)
got = tmp.replace("%e9", "%C3%A9")   # 第二跳
assert got == "caf%C3%A9"
```

或抽到**同檔 helper / 同 package util**。  
helper 展開若只做 test 內一跳，仍漏。

| 欄位 | 內容 |
|------|------|
| **要關到哪** | 有界 SSA + 跨函式 inlining 上限 |
| **極限** | 永遠存在 k+1 跳 |
| **嚴重度** | High |

---

### 2. Binding 修了 → 改 fixture / parametrize 資料

#86a 若只追 unit 內 `Name =`：

```python
@pytest.fixture
def expected():
-    return 105.3
+    return buggy_total(...)   # 或硬編 bug 輸出

def test_x(expected):
    assert invoice_total(...) == expected  # 行可完全不變
```

或改 `@pytest.mark.parametrize` 的**期望欄**，assertion 形狀不變。

| 欄位 | 內容 |
|------|------|
| **靜音度** | ★★★★ |
| **修法難度** | 中高（fixture 跨檔、conftest、parametrize 結構） |
| **嚴重度** | High |

---

### 3. Opaque 收成 per-finding → 改「測試真依賴的 opaque 輸入」

不再摸無關 `deploy.sh`，改：

- 改 golden 旁邊的 **fixture JSON**（若仍 opaque）  
- 改 **snapshot** 配 bug（`SNAPSHOT_CODE_COCHANGE` 要「無 test logic change」；同時加假 test 邏輯 flag 可能繞）  
- 改 **C 擴展 / .so 源**（永遠 opaque，且可能是真 runtime）

| 欄位 | 內容 |
|------|------|
| **嚴重度** | Medium–High |
| **備註** | 比「無關三行 JSON」更像真實修 bug，人審更難抓 |

---

### 4. Runner 列表補齊 → 間接呼叫

```yaml
- run: ./scripts/ci_entry.sh   # greenwash 認得，內容乾淨
```

```sh
# ci_entry.sh
exec ./scripts/real_test.sh
# real_test.sh: pytest || true
```

或 Makefile `include common.mk` 鏈、tox → nox → shell。

| 欄位 | 內容 |
|------|------|
| **模式** | 枚舉永遠落後於 indirection |
| **嚴重度** | High（若 content 閘門只看「直接含 pytest 的檔」） |

---

### 5. collect_ignore 修了 → plugin / 動態 collection

```python
def pytest_ignore_collect(collection_path, config):
    if "billing" in str(collection_path):
        return True
```

或 `pytest_collection_modifyitems`：**remove** items vs **mark skip**。  
誠實 `--runslow` 與作弊刪檔，若只當「有 hook = 有 control」而不解析 body，無法區分（THREATMODEL 已承認，FP 亦開）。

| 欄位 | 內容 |
|------|------|
| **嚴重度** | High |
| **修法** | IR 需理解 hook body（高成本、高 FP 風險） |

---

### 6. Custom helper 展開 → test 內 mock 換被測物

#60 只抓 conftest **first-party** monkeypatch：

```python
# 在 test 裡，不是 conftest
monkeypatch.setattr(billing, "invoice_total", lambda *a: 105.3)
assert invoice_total(...) == 105.3  # 測的是 stand-in
```

或 `unittest.mock.patch`、`pytest-mock`、`respx` 把 HTTP 回成「對的」。  
prod 與 assertion 字面都可不動。

| 欄位 | 內容 |
|------|------|
| **靜音度** | ★★★★★ |
| **修法難度** | 高（假陽性極多：合法 stub time/network） |
| **嚴重度** | Critical（實戰） |

---

### L1 遷移對照表

| 你補的 | 攻擊者遷移到 |
|--------|----------------|
| 單行 subject wrap | 兩跳、fixture、跨函式 util |
| expected 綁定 diff | parametrize 欄、conftest fixture、外部 JSON |
| opaque 不全 diff 豁免 | 真依賴的 data/C 擴展、有呼叫的葉符號微改 |
| runner 檔名表 | 間接 script、include 鏈、容器 entrypoint |
| collect_ignore 集合 | plugin hook body、動態 path |
| custom helper 展開 | mock、第三方 assert lib、深度 helper |
| imperative guard | `skipif(helper())`、xfail、新檔 xfail |

**不變的模式：** 每關一個「字面 / 一跳 / 列表」，攻擊者加**一層 indirection** 或換一個**未建模方言**。

---

## L2 — 更深、第一輪未當主角的打穿面

### 7. D6：`skipif(helper(...))` 永遠偏 grant

```python
@pytest.mark.skipif(should_skip(), reason="compat")
def test_failing():
    ...
```

`should_skip()` 若 unevaluable → MAYBE → **不**判 always-true → 拿 `COMPAT_GATE`。  
helper 內 `return True` 可靜音。

| 欄位 | 內容 |
|------|------|
| **狀態** | 刻意 trade（THREATMODEL #6） |
| **緊了會怎樣** | 擋真實 compatibility skip |
| **嚴重度** | High（informed 可讀 gating 源碼專打） |

---

### 8. `xfail(strict=False)` 合法化失敗

非 strict xfail = 失敗也算過。  
base 無、head 加上，且條件 unevaluable / 帶 compat token → D6 留 warn。

| 欄位 | 內容 |
|------|------|
| **本質** | 把 fail **合法化**，不是弱化 assert 格子 |
| **嚴重度** | Medium–High |

---

### 9. 新測試檔天生 skip/xfail（#82 刻意 scoped）

新建 `tests/test_bug_repro.py` 整檔 `@pytest.mark.xfail` / skip → **靜音**（當 bug repro）。

攻擊組合：失敗用例「搬」成新檔並 xfail；舊檔刪失敗——刪除側可能被 `TEST_DISABLED` 抓，但 **RESTRUCTURED / 新檔不報** 需實測組合。

| 欄位 | 內容 |
|------|------|
| **嚴重度** | Medium |

---

### 10. Alignment 攻擊（結構層，不是單 rule）

| 手法 | 效果 |
|------|------|
| **大量 rename + rewrite** 撐爆 `MAX_UNPAIRED=64` | `alignment=degraded`，配對變差 |
| **Fingerprint 碰撞**（Jaccard ≥ 0.8） | 無關 unit 被 pair，弱化讀成 rewrite |
| **#84d 翻轉比較 + 換 subject** | `ASSERT_SUBSTITUTED` **by design** 吞掉 |
| **期望不變的 subject rename** | 當 rename；SUBSTITUTED 不報（#84b residual） |
| **1 assert → 弱 precondition + 真 oracle**（#85） | 現在是 FP；修 FP 若寫太寬 → 變 bypass |

| 欄位 | 內容 |
|------|------|
| **嚴重度** | Medium–High |
| **備註** | 對齊參數在 SPEC 凍結；動對齊 = 版本級變更 |

---

### 11. 未分類 assertion form（strength = null）

自訂 matcher、部分 `assertRaises` 家族、hamcrest——**不進 weakening 比較**。

- 移除仍可能 `ASSERT_REMOVED`  
- **換成另一個 unclassifiable** → `strength_change=None`，SUBSTITUTED 條件可能不滿足 → 靜音  

| 欄位 | 內容 |
|------|------|
| **狀態** | Fail-safe：不猜、不噪（SPEC） |
| **嚴重度** | Medium–High（依賴 codebase 風格） |

---

### 12. 環境 / 外部 oracle

```python
assert os.environ.get("FORCE_OK") or result == 105.3
# 或 CI 注入 EXPECT=...，測試讀 env
```

或測 **DB seed / 網路 mock 回傳**；diff 只改 seed SQL（data / opaque）。

| 欄位 | 內容 |
|------|------|
| **為何漏** | 不執行、不看 runtime env |
| **嚴重度** | Medium |

---

### 13. Hypothesis / property / fuzz

```python
@given(st.integers())
def test_prop(x):
-    assert f(x) == model(x)
+    assert True
```

改 strength 可能被抓；但：

- 縮 **strategy** 到永遠過的子集  
- 用 `assume()` 濾掉失敗域  

前端幾乎無 property-test 模型。

| 欄位 | 內容 |
|------|------|
| **嚴重度** | Medium（用 Hypothesis 的專案） |

---

### 14. Snapshot 合法更新路徑

Prod 真改一點（repair）+ 重寫 golden 配 bug。  
`SNAPSHOT_CODE_COCHANGE` 要無 test logic；有 repair 時其他 oracle 也降 warn。

| 欄位 | 內容 |
|------|------|
| **本質** | 誠實修 + 偷偷改 snapshot → **人審**問題 |
| **嚴重度** | Medium |

---

### 15. Allowlist / 設定攻擊（base 側 + 社工）

- 合法 `greenwash allow` 後 commit（審計可見）  
- 說服人加 exemption  
- **兩步：** PR1 在 base 關 `disabled_detectors`；PR2 再作弊  
- `on_engine_error=pass` 配解析錯誤邊角  

| 欄位 | 內容 |
|------|------|
| **嚴重度** | Medium（需權限或社工） |
| **防禦** | base policy 鎖、禁止 PR 關 detector、allow 需雙人 |

---

### 16. 非 Python / 多語言 monorepo

JS/TS、Go、Rust——v0.1 **prod 幾乎 opaque、test 幾乎不解析**。  
Monorepo 裡改 Python 測試旁的 **TS 假 prod** 仍可能餵 opaque。

| 欄位 | 內容 |
|------|------|
| **狀態** | v0.2 frontend 前是整大陸 |
| **嚴重度** | Critical（polyglot repo） |

---

### 17. 一跳 call graph 不夠深（THREATMODEL #5）

- **誠實 FP：** test → `format()` → `compute()` 改三層下 → 無 repair → 誤擋  
- **攻擊：** 在**測試有呼叫的葉函式**塞一行微改拿 `REPAIR_EVIDENCE`  

Symbol fingerprint 太粗 → 小改就有 evidence；太細 → FP。永遠是 trade。

| 欄位 | 內容 |
|------|------|
| **嚴重度** | Medium |

---

### 18. `unittest.skipIf` / 其他 runner 方言

gating 註解：**unittest.skipIf 刻意未進 D6**。  
可能 credit 不一致，或 imperative 以外的 skip 方言漏抓。

| 欄位 | 內容 |
|------|------|
| **嚴重度** | Low–Medium |

---

### 19. Meta：對 greenwash 自身 / 其 fixture

改 greenwash 自己的測試或 release gate（D-031 已發生過）。  
組織用 greenwash 掃 greenwash 時，**meta 層**永遠敏感。

| 欄位 | 內容 |
|------|------|
| **嚴重度** | High（dogfood 情境） |

---

### 20. 時間 / 多 range 視窗

- squash 前多 commit；本地 hook 只看 worktree 最後態  
- **分 PR：** PR1 加 skip「暫時」、PR2 刪 skip 並弱化——各 PR 可能過  
- `GREENWASH_TODAY` 污染 allow 過期邏輯（生產不該設）  

| 欄位 | 內容 |
|------|------|
| **嚴重度** | Medium–High（process） |
| **防禦** | 掃 merge-base 整串、required check on merge |

---

## 補完前 10 之後的實戰攻擊優先序（新表）

| 順位 | 招 | 靜音度 | 補 detector 難度 | 層 |
|------|----|--------|------------------|-----|
| 1 | **改 prod 配合舊測試** | ★★★★★ | 不可能（需執行/規格） | L0 |
| 2 | **test 內 mock/patch 換被測物** | ★★★★★ | 高（假陽性多） | L1 |
| 3 | **改 fixture / parametrize 期望資料** | ★★★★ | 中高 | L1 |
| 4 | **D6 unevaluable helper skip** | ★★★★ | 中（trade-off） | L2 |
| 5 | **兩跳+ dataflow / 跨函式 util** | ★★★★ | 高 | L1 |
| 6 | **xfail 合法化失敗** | ★★★ | 中 | L2 |
| 7 | **多 commit / 多 PR 洗白** | ★★★★ | 需 process，非單 diff | L0 |
| 8 | **alignment / 翻轉比較 #84d** | ★★★ | 中（by design 鬆） | L2 |
| 9 | **unclassified form 互換** | ★★★ | 中 | L2 |
| 10 | **plugin 動態 ignore collect** | ★★★★ | 高（解 hook body） | L1 |
| 11 | **非 Python monorepo opaque** | ★★★★ | 新 frontend | L2 |
| 12 | **env / 外部 seed 當 oracle** | ★★★ | 需執行或契約 | L2 |

---

## 真正能「封頂」的：系統設計，不是第 20 個 rule

1. **強制 CI + 不可從 PR 關 detector**（base 側 policy 鎖）  
2. **任務級 `oracle_freeze` + 人審** 對 high-risk 變更  
3. **執行層陪跑**（mutation、重跑 fail 測試、sandbox 比 base/head 行為）——greenwash 刻意不做  
4. **多 diff 窗口**（stack 整串 / merge-base 全 PR，不只最後一個 commit）  
5. **接受 residual rate**：公開 `FAILURES.md`，當 cost 函數不是 0-miss  

```
單 diff 靜態語意
        │
        ▼
   greenwash（提高作弊成本）
        │
        ├── 仍漏：改 prod、mock、多提交、等價改寫
        │
        ▼
   process + 執行層陪跑 + 人審
        │
        ▼
   可接受的殘餘風險
```

---

## 與第一輪報告的關係

| 文件 | 內容 |
|------|------|
| [redteam-weaknesses.md](./redteam-weaknesses.md) | 第一輪 10 洞：現況可打、可補 detector 為主 |
| **本文件** | 假設第一輪已防：L0 無解 + L1 遷移 + L2 更深洞 |

### 建議路線圖（接在第一輪 P0–P3 之後）

| 順位 | 項目 | 層 |
|------|------|-----|
| P4 | fixture / parametrize 期望資料 diff | L1 |
| P4 | test-scoped mock/patch 瞄準 first-party（極窄、高 FP 風險） | L1 |
| P5 | 有界多跳 dataflow（k=2） | L1 |
| P5 | plugin hook body 粗分 remove vs mark | L1/L2 |
| P6 | D6 helper：有限內聯同檔函式 | L2 |
| — | 多 commit 掃、CI 鎖 detector、執行陪跑 | process |
| — | #1 改 prod | 永不在工具內關 |

---

## 結論

1. **前 10 防住 ≠ 打不穿。**  
2. **永遠打得穿：** 改 prod、不跑工具、多提交洗白、測試本來就沒牙。  
3. **下一輪主戰場：** mock/fixture 資料、D6 helper skip、兩跳 dataflow、plugin collection、alignment by-design 鬆、非 Python opaque。  
4. greenwash 的誠實上限仍是文件原句：

   > **A deterministic tripwire that raises the cost of cheating** — not a guarantee of no cheating.

5. 補 detector 會把攻擊者**推向 indirection 與 process 縫隙**；要再壓成本，必須 **CI 強制 + 多窗口 diff +（可選）執行層陪跑 + 人審**，而不是無限加 rule。

---

## 參考

| 文件 | 用途 |
|------|------|
| `docs/redteam-weaknesses.md` | 第一輪 10 弱點 |
| `THREATMODEL.md` | 公開 bypass、#1/#3/#5/#6 極限 |
| `benchmarks/FAILURES.md` | 未關閉列、agent 逃脫 |
| `SPEC.md` | 對齊參數、E/D 表凍結 |
| `src/greenwash/gating.py` | D6、repair evidence |
| `src/greenwash/ir/diffalign.py` | 對齊 / degraded |
| `src/greenwash/frontends/python/frontend.py` | 分類與 binding 邊界 |

回報新作弊：`.github/ISSUE_TEMPLATE/send-us-a-cheat.md`。
