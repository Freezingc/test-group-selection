## Material Passport

- Origin Skill: ARS `experiment-agent`
- Origin Mode: validate；完整 E1 結果與已凍結選擇的唯讀個案審計
- Origin Date: 2026-10-19，Asia/Shanghai
- Verification Status: ANALYZED；本審計未重跑生成或官方評測
- Version Label: e1-case-audit-v1
- Stage: E1 探索性證據；E0 不併入分母，E2 未執行
- Review Provenance: 同一上下文的 native audit worker；不是跨模型獨立審查或盲審
- Scope: 僅修改本文件；未改協議、配置、原始資料或結果，未在 host 執行候選原始碼，未啟動 GPU

## 判斷與完整分母

**H1 在本次自然生成資料中存在，H2 尚未建立，現有證據不支持擴大到 E2。** 強基線 ACES-C 在140題中選對110題，而池內有正確程式的題目為121題，留下11題選擇錯誤。這支持存在剩餘空間；不能把11題全部解釋為來源分組可解決的邏輯錯誤，其中包括零可見測試的 Mbpp/563。

來源分組 Perturbed 相對 Top-2 的全部增益，去除跨選擇器重複後只有 **Mbpp/787、Mbpp/459、Mbpp/734**，五選擇器均無 coverage loss。三題都已被行為多樣性 Diverse 覆蓋；兩題的20個匹配隨機分組全部覆蓋正確候選，另一題為12/20。三題的關鍵刪組均將正確／錯誤候選變成可見分數平局，再由預先固定的 hash 選中正確候選。因此個案不足以支持「真實來源分組具有額外信息」。

以下均為同一140題上的正確覆蓋題數；每題16候選，集合上限 k=2 且按原始 source SHA 去重。Random 是20個預先固定 seed 在題內取平均後的等價題數，分母仍為140，不是2,800個獨立樣本。

| Selector | Base | Top-2 | Diverse | Perturbed | Random mean | Perturbed 對 Top-2 gain / loss |
|---|---:|---:|---:|---:|---:|---|
| uniform | 110 | 111 | 116 | 112 | 112.05 | 787 / 無 |
| aces_c | 110 | 111 | 116 | 112 | 112.50 | 787 / 無 |
| dedup_uniform | 104 | 109 | 115 | 110 | 110.25 | 787 / 無 |
| group_equal | 110 | 111 | 116 | 112 | 112.10 | 787 / 無 |
| group_rep | 108 | 113 | 116 | 115 | 114.70 | 459、734 / 無 |

主基線 ACES-C 的 Perturbed − Top-2 為 **+0.714百分點**，95%描述性配對 bootstrap 區間 `[0, 2.143]`；相對 Diverse 為 **−2.857百分點** `[-6.429, 0]`，相對 Random mean 為 **−0.357百分點** `[-0.964, 0]`。group_rep 相對 Random mean 為 **+0.214百分點** `[-0.429, 1.000]`，相對 Diverse 為 **−0.714百分點** `[-2.857, 1.429]`。這些是10,000次按題重採樣的 percentile 區間，seed=20261019；五選擇器×三個配對比較共15組未校正描述性區間，不作確認性顯著判定，也不把包含0的區間寫成證明無效果。

來源審查最初在 hidden labels 完成前進行；本版只在 evaluation receipt 為 completed、140題完整且 SHA 鏈核實後讀取全量官方 labels／結果。沒有用 partial labels 推論，沒有讀取官方隱藏輸入或參考程式。下文 cXX、gXX 指同題 `candidate/XX`、`tests/XX`；label=1 指官方 MBPP+ base 與 plus 均 pass，label=0 表示不滿足兩者。

## 全部 gain / loss 個案

| Task / 有 gain 的 selector | Top-2 → Perturbed（括號為官方 label） | 刪組 winner 票 | Diverse coverage | 匹配 Random coverage |
|---|---|---|---:|---:|
| Mbpp/787；uniform、aces_c、dedup_uniform、group_equal | `[c10(0),c02(0)]` → `[c10(0),c13(1)]` | c10:1、c13:1 | 1 | 各20/20 |
| Mbpp/459；group_rep | `[c07(0),c00(0)]` → `[c07(0),c02(1)]` | c07:7、c02:1 | 1 | 12/20 |
| Mbpp/734；group_rep | `[c01(0),c10(0)]` → `[c01(0),c13(1)]` | c01:6、c13:2 | 1 | 20/20 |

這是所有五方法相對各自 Top-2 的完整事件表；787的四筆是同一題，不算四個獨立機制案例。三題相關候選的可見執行沒有 timeout 或缺失依賴，增益不直接來自將 NumPy／格式失敗候選加入集合。

### Mbpp/787：只有一個區分列，刪除後完全平局

題目為字串中 `a` 後接三個 `b` 的匹配。16候選有15個不同 source；請求的64條測試中56條解析失敗，剩下兩個來源組，各4條。完整8列的所有行只有兩種：c02、c10 為 `01111111`，其餘14候選為 `01111101`。c02、c10 都用 `re.search('abbb$', s)`，要求匹配位於字串末端；c13 用 `re.search('ab{3}', s)`，允許匹配後仍有字元，官方 label 為1。c03用 `re.match`，與c13可見行相同，但官方 label 為0，說明這個可見等價類本身仍不可辨識正確性。

| 完整列 index | Test ID 尾段 | 生成 assertion 的輸入／期望 | c10 | c13 |
|---:|---|---|---:|---:|
| 0 | g03/t01 | `'abc' → True` | 0 | 0 |
| 1 | g03/t03 | `'abbb' → True` | 1 | 1 |
| 2 | g03/t05 | `'a' → False` | 1 | 1 |
| 3 | g03/t07 | `'bba' → False` | 1 | 1 |
| 4 | g04/t02 | `'abb' → False` | 1 | 1 |
| 5 | g04/t03 | `'abbb' → True` | 1 | 1 |
| 6 | g04/t06 | `'abbbbbc' → False` | 1 | 0 |
| 7 | g04/t07 | `'' → False` | 1 | 1 |

第0列的正例期望明顯不符題意；唯一區分行的第6列支持末端錨定語義，與官方通過的 c13 語義不一致。四方法完整矩陣都先排 c10、c02；刪 g03 後 winner=c10，刪 g04 後16行全部相同，winner=c13。uniform 此時所有候選得3分；ACES-C 刪除常量列後沒有區分列，所有分數為0，metadata 為 `no_discriminating_tests`。兩者都由固定 hash 決定 winner，沒有形成正確候選的嚴格分數優勢。

Diverse 已選 `[c10,c13]`；四方法的20個匹配隨機分組也全選此覆蓋組合。唯一區分列無論落入哪個刪除組，刪掉該組均能令行相同，因此這個 gain 能由刪列／平局機制解釋。group_rep 的原始 Top-2 已含 c13，故該方法在本題沒有 gain。

### Mbpp/459：字符域語義差異，代表列刪除後平局

16候選、15個 source，64條測試分8組。c07、c00 保留所有「非 uppercase」字元，完整可見行相同、54/64；c02只保留 `islower()` 字元，所以會額外丟棄數字、標點及空白。官方 c07/c00 label=0、c02 label=1；公開文字「移除 uppercase」對非字母處理未充分釐清，不能將前兩者僅憑自然語言標成明確實作錯誤。這是可核對的語義分歧及 benchmark 判定，不是執行環境差。

為完整復核，兩種相關行如下（64列依原順序）：

```text
c07 = c00: 1111110111110101111011111111110111101011110111101111111111111110
c02:       0110110011100001111001011111100011100010110111001111011011001110
```

group_rep 原代表列為 `[1,8,17,31,35,42,48,57]`，c07/c00得6分、c02得5分；c02原排名第14。刪 g03 去掉代表列31，即 g03/t07 的 `remove_uppercase('Python3.8') == 'ython3.8'`；c07通過、c02回傳`'ython'`而失敗。刪除後 c07、c02均5分，固定 hash 令 c02勝出，形成1票；另7組刪除均 c07勝出。不是刪除後 c02得分嚴格超過 c07。

Diverse 也選 `[c07,c02]`。匹配隨機 group_rep 的12/20種子覆蓋 c02，種子為 `[0,2,6,7,9,10,11,13,14,15,17,19]`；真分組在這一題相對 seed mean 為+0.4個等價題。其餘四方法的真 Perturbed 及20個 Random 均未覆蓋，而 Diverse 均覆蓋。這是一個有限的真分組優於部分隨機切法的案例，不能抵銷全體結果或證明來源機制優於 Diverse。

### Mbpp/734：把子陣列乘積誤算為和，錯誤期望支持錯誤語義

16候選皆不同 source，64條測試分8組。c01對每個子陣列累加元素；c10用 `sum(a[i]*(i+1)*(n-i))`，同樣計算所有子陣列元素和，而非題目要求的乘積和。c13逐個相乘後累加，官方 label=1；c01/c10 label=0。公開範例 `[1,2,3] → 20` 剛好使兩種算法相同，無法消除這種自然邏輯錯誤。

```text
c01 = c10: 1010011010000000111111001000110010111110100001101111001110101011
c13:       1001111010000000110011001000110010100110100001101011001011010111
```

完整可見分數 c01/c10為34/64、c13為30/64。group_rep 代表列 `[2,9,22,24,35,44,50,59]` 使前兩者得4分、c13得3分。兩個會改變 winner 的刪組為 g00、g04：

| 刪除組 / 代表列 | 生成測試 | 子陣列「和」 | 正確乘積和 |
|---|---|---:|---:|
| g00 / index2，t02 | `[-1,-2,-3] → -20` | -20（pass） | -4（fail） |
| g04 / index35，t03 | `[1,-1,1,-1] → 0` | 0（pass） | -2（fail） |

兩個生成 expected 都符合錯誤的「和」算法；刪除任一組後 c01與c13均3分，hash讓c13勝出，票為2；其他6次仍c01勝。Diverse 已選 `[c01,c13]`，20/20匹配隨機 group_rep 也覆蓋 c13，故本題沒有真來源特異性。其餘四方法真 Perturbed 均未救援；它們的 Random 覆蓋次數依 uniform、aces_c、dedup_uniform、group_equal 順序為1、7、0、2/20，亦顯示刪列機會不限於真來源邊界。

## 執行環境與格式限制

[execution-audit.json](../artifacts/runs/e1-v1/execution-audit.json) 統計140題、2,240候選、138,464個可見執行 cell：82,783 pass、30,786 assertion_fail、24,823 program_error、72 timeout。沒有 MemoryError、ImportError 或 ChildProcessExit；有64個 ModuleNotFoundError。timeout 與 assertion_fail 在二元矩陣中均為0；不能僅由名稱不同推斷方法利用了時間資訊。

| Task | 靜態來源與記錄證據 | 完整選擇／官方結果的含義 |
|---|---|---|
| Mbpp/224 | c02–c07、c11–c15 ×5個負數測試=55 timeout。負數右移最終停在−1，`while n`不結束；生成 expected 對同一−1分別為−1、32、64，沒有一致位寬 | 16行完全相同51/56，全部方法 Top-2/Perturbed=c15/c13。11個 timeout 候選官方 label 均1；可見負數終止性問題不能直接等同官方錯誤，也沒有帶來組間 gain/loss |
| Mbpp/583 | 5個無緩存 Catalan 遞迴在 g06/t07 的 n=20 timeout。靜態呼叫數為 `3**20`；生成 expected=1679612445727374400，但 `C20=comb(40,20)//21=6564120420` | 其餘11候選在該列 assertion_fail，16行皆63/64；所有方法選c03/c08。5個慢候選 label均1；這條錯誤 expected 即使延時回傳也不會使正確數值 pass |
| Mbpp/739 | c05/c15對n=100、1000逐項搜尋三角數，共8 timeout；達相應位數的索引約需50、500位，生成 expected 均不可能達到要求位數 | 四條 concern 列全0；c05/c15仍會因其他列得分進集合，兩者 label均0。此題五方法無 Perturbed 相對 Top-2 的 coverage 得失，不能由全0列辨識慢／錯算法 |
| Mbpp/765 | c05/c07/c10/c15於g00/t00的n=0無法使已遞增的計數等於0，共4 timeout；公開範例未釐清n=0的域 | 該列9 pass、4 timeout、2 program_error、1 assertion_fail，確有區分力。dedup_uniform刪g00給c10一票，group_rep集合含c07；四個 timeout 候選label均0，本題仍無 coverage gain/loss |
| Mbpp/129 | 唯一非stdlib導入：c12的`numpy`；可見`-S`環境64次ModuleNotFoundError，完整行全0；生成提示要求標準庫 | c12官方label=1，確認可見與hidden環境可用性不一致。它在五方法原排名均第16，全部105種真／隨機設定的Top-2、Perturbed、Raw W均不含它；沒有直接環境救援gain，但全0行仍參與ACES估權，不能聲稱環境差完全無影響 |

AST 靜態計數為 **319/2240（14.24%）候選含獨立頂層 `python` 表達式，分布101題**；319行全部為0。318個有測試的候選共19,969個 cell 都為 `NameError: name 'python' is not defined`；另一個是零測試題563的c08。這是格式／抽取殘留，不能將cell數當作獨立邏輯錯誤樣本。非stdlib導入只有上述 NumPy 1個模組／1候選／1題；靜態AST沒有動態或相對導入標記，不能保證發現一切動態載入。

五方法真分組的 base、Top-2均沒有上述殘留；group_rep 在 Mbpp/555的 Perturbed 將c04替換成c09（label=0，64個NameError）。刪g05後七個代表列 `[6,9,23,28,37,49,61]` 對16候選全部得0分，hash讓c09拿到一票；這是資訊歸零後的格式失敗暴露，不是新解題邏輯。Random另有group_rep的641/seed15、279/seed4選入殘留。均保留原結果，不事後修復或剔除；555不屬本次coverage gain/loss。

唯一零測試題 Mbpp/563的8批測試均解析失敗，16候選及題目仍在固定分母；它屬ACES-C的11題H1剩餘錯誤之一。其餘10題為429、644、459、610、558、759、597、787、734、102。這說明H1包含工程與測試資訊不足，不能僅憑此審計估計「純語義選擇錯誤」盛行率。三道增益題沒有缺依賴或timeout，仍不足以把完整總體效果宣稱為完全排除了環境混雜。

## 核對範圍與可重查證據

[summary.json](../artifacts/runs/e1-v1/summary.json)、[execution-audit.json](../artifacts/runs/e1-v1/execution-audit.json) 與本次凍結配置對應。原始 `raw/tasks.jsonl`、`raw/selections.jsonl`、`evaluation/labels.json` 等檔案見 [E0–E1 release archive](https://github.com/Freezingc/test-group-selection/releases/tag/e0-e1-v1)，不以原始碼樹中的忽略路徑作連結。

本審計核對 completed matrix／selection manifest、config、evaluation receipt及實際檔案 SHA、完整140題ID、全部候選 labels，並從每題二元標籤重算五方法全部gain/loss及個案20-seed覆蓋數。三題的完整矩陣、相關候選原始碼、生成assertion、代表列、刪組winner及source votes均逐項比對。Random只改刪除分組，完整矩陣的Base／Top-2維持原始F，刪除後亦用保留下來的真來源組重新估分；沒有隱藏label輸入選擇器。本文件的 ANALYZED 標記不代替主流程另行保存的 deterministic replay／archive驗證receipt。

| Artifact | SHA-256 |
|---|---|
| raw/tasks.jsonl | `52a9fb78cd4e2d726df57e17dc83b554747f6c50dc0f78a8f94f9af4b5bbacd1` |
| tasks.manifest.json | `2964868e53ff23cc0e2cf114731ebd4aa1917bc1bc3dd645dd2d4f216089f87f` |
| raw/selections.jsonl | `e99830b400bfcb107363dee856da100a3f693ad1bc2f9d877a307efd17994287` |
| selections.manifest.json | `18160156cbad9ce85b8f5a35ca8788d1894c99b128e22024dadacd3ee26c8592` |
| evaluation/labels.json | `348622322ac0b27d56c84e06bd5fd3e7613a2ac7db1a30c1ee189b24febba1eb` |
| evaluation.receipt.json | `49c6a60d8e59c2081bfdbc3378e88981a11501de52cecc278a05e9057f59c55f` |
| configs/e0-e1-v1.json | `ff38b4d4676c37cf4066e425c7f276aa3d2bc4e219f6cfb3ccedd1c8f141f9b7` |
| summary.json | `cf79ed11c111fc77ea02c4a84ed4a95f2f4eb7cded20e2f49d69e3baad8f6329` |
| execution-audit.json | `8fc34c93fced86f2087a2b431973247e56e8a4ce291b3c39fc6b747df902a6b5` |

program-child seconds最大0.5包含timeout預算記錄；p50約0.001233、p95約0.004756、p99約0.004985。candidate wall合計11,203.10秒、最大7.055秒是重疊工作的累積量，不是matrix stage的實際wall，也未據此推論加速收益。

ARS 統計 fallacy scan：**11/11 checked，整體 CAUTION**。①Simpson：沒有跨不同分母聚合，五方法分列，但未作題型分層泛化；②ecological：推論單位保持task；③Berkson：固定開發集／單模型限制外推；④collider：未按hidden結果重新篩題或加控制變量；⑤base-rate：同列pool121/140與base110/140；⑥regression-to-mean：沒有從挑出的三題估計後續收益；⑦survivorship：保留零測試、格式失敗與全部140題；⑧look-elsewhere：披露五方法全部gain/loss及15組未校正區間；⑨forking paths：配置與選擇在hidden前凍結，個案為事後解釋；⑩correlation/causation：未把刪組平局當作來源質量的因果證據；⑪reverse causality：選擇先於官方label，未由正確性反選winner。單模型、單開發集、低事件數與環境差限制結論，沒有證明所有來源分組或後續人工審核都無價值。
