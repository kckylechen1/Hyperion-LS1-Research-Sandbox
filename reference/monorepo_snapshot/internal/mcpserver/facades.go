package mcpserver

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

var (
	tachiClockNow        = time.Now
	shanghaiLocationOnce sync.Once
	shanghaiLocation     *time.Location
)

func getShanghaiLocation() *time.Location {
	shanghaiLocationOnce.Do(func() {
		loc, err := time.LoadLocation("Asia/Shanghai")
		if err != nil {
			loc = time.FixedZone("CST", 8*3600)
		}
		shanghaiLocation = loc
	})
	return shanghaiLocation
}

// ── Facade types ──────────────────────────────────────────────

type facadeAction struct {
	Action   string
	Method   string         // RPC method to dispatch to (or hypertachi action if prefixed hypertachi.)
	Required []string       // required params for this action
	Defaults map[string]any // default param values
	ReadOnly bool
}

type facadeSpec struct {
	Name        string
	Description string
	Actions     map[string]facadeAction // keyed by action name
	ReadOnly    bool                    // true only if ALL actions are read-only
}

// ── Facade definitions ────────────────────────────────────────

var facadeSpecs = []facadeSpec{
	{
		Name: "hapi_market",
		Description: "Market data desk — real-time quotes, K-lines, market temperature, intelligence, and capital flow. " +
			"Actions: quote, quote_batch, klines, gate, intel, flow.",
		ReadOnly: true,
		Actions: map[string]facadeAction{
			"quote":       {Action: "quote", Method: "quote.get", Required: []string{"symbol"}, ReadOnly: true},
			"quote_batch": {Action: "quote_batch", Method: "quote.batch", Required: []string{"symbols"}, ReadOnly: true},
			"klines":      {Action: "klines", Method: "kline.get", Required: []string{"symbol"}, ReadOnly: true},
			"tickerboard": {Action: "tickerboard", Method: "tickerboard.view", ReadOnly: true},
			"gate":        {Action: "gate", Method: "market.gate", ReadOnly: true},
			"intel":       {Action: "intel", Method: "intel.market", ReadOnly: true},
			"flow":        {Action: "flow", Method: "capital.flow", Required: []string{"symbol"}, ReadOnly: true},
		},
	},
	{
		Name: "hapi_scanner",
		Description: "Stock screening desk — market-wide discovery, hot stocks, condition scans, peer comparison, and symbol lookup. " +
			"Actions: discover, hot100, scan, peers, profile, symbols.",
		ReadOnly: true,
		Actions: map[string]facadeAction{
			"discover": {Action: "discover", Method: "discovery.scan", ReadOnly: false},
			"hot100":   {Action: "hot100", Method: "discovery.hot100", ReadOnly: true},
			"scan":     {Action: "scan", Method: "scan.market", ReadOnly: true},
			"peers":    {Action: "peers", Method: "peers.find", Required: []string{"query"}, ReadOnly: true},
			"profile":  {Action: "profile", Method: "stock.profile", ReadOnly: true},
			"symbols":  {Action: "symbols", Method: "symbols.list", Defaults: map[string]any{"top_n": 5, "fields": "compact"}, ReadOnly: true},
		},
	},
	{
		Name: "hapi_analyst",
		Description: "Analysis desk — V8 snapshot, triage, and deep analysis. " +
			"Actions: triage, snapshot, core, core_batch, batch, parity, analyze. " +
			"For V8 tactical assessment, prefer action=batch with format='json' and explicit fields/presets such as ['hunt']. " +
			"COLD-CACHE: if data_freshness.cache='cold' after one retry, report and stop.",
		ReadOnly: true,
		Actions: map[string]facadeAction{
			"triage":     {Action: "triage", Method: "analysis.triage", Required: []string{"symbol"}, ReadOnly: true},
			"snapshot":   {Action: "snapshot", Method: "snapshot.core", Required: []string{"symbol"}, Defaults: map[string]any{"include_trap": true}, ReadOnly: true},
			"core":       {Action: "core", Method: "snapshot.core", Required: []string{"symbol"}, ReadOnly: true},
			"core_batch": {Action: "core_batch", Method: "snapshot.core_batch", Required: []string{"symbols"}, ReadOnly: true},
			"batch":      {Action: "batch", Method: "snapshot.core_batch", Required: []string{"symbols"}, Defaults: map[string]any{"include_trap": true}, ReadOnly: true},
			"parity":     {Action: "parity", Method: "snapshot.parity", Required: []string{"symbols"}, ReadOnly: true},
			"analyze":    {Action: "analyze", Method: "analysis.full", Required: []string{"symbol"}, ReadOnly: true},
		},
	},
	{
		Name: "hapi_portfolio",
		Description: "Portfolio desk — positions, fund state, trade records, and watchlist management. " +
			"Actions: positions, summary, diff, journal, trades, watchlist, fund_meta, daily, watchlist_add, watchlist_remove, watchlist_prune. " +
			"journal/trades/watchlist support offset pagination.",
		ReadOnly: false,
		Actions: map[string]facadeAction{
			"positions":        {Action: "positions", Method: "portfolio.positions", ReadOnly: true},
			"summary":          {Action: "summary", Method: "portfolio.summary", ReadOnly: true},
			"diff":             {Action: "diff", Method: "portfolio.diff", ReadOnly: true},
			"journal":          {Action: "journal", Method: "journal.list", Defaults: map[string]any{"limit": 10, "fields": "compact"}, ReadOnly: true},
			"trades":           {Action: "trades", Method: "trade_history.list", Defaults: map[string]any{"limit": 10, "fields": "compact"}, ReadOnly: true},
			"watchlist":        {Action: "watchlist", Method: "watchlist.list", ReadOnly: true},
			"fund_meta":        {Action: "fund_meta", Method: "portfolio.fund_meta", ReadOnly: true},
			"daily":            {Action: "daily", Method: "daily_summary.get", ReadOnly: true},
			"watchlist_add":    {Action: "watchlist_add", Method: "watchlist.add", Required: []string{"symbol"}, Defaults: map[string]any{"category": "watch"}, ReadOnly: false},
			"watchlist_remove": {Action: "watchlist_remove", Method: "watchlist.remove", Required: []string{"symbol"}, ReadOnly: false},
			"watchlist_prune":  {Action: "watchlist_prune", Method: "watchlist.prune", Defaults: map[string]any{"ttl": 3, "dry_run": false}, ReadOnly: false},
		},
	},
	{
		Name: "hapi_trade",
		Description: "Trading execution desk — buy, sell, position sync, stop-loss, and radar subscription. " +
			"Actions: buy, sell, sync, stops, watch_add, watch_remove.",
		ReadOnly: false,
		Actions: map[string]facadeAction{
			"buy":          {Action: "buy", Method: "portfolio.buy", Required: []string{"symbol", "shares", "price", "reason"}, ReadOnly: false},
			"sell":         {Action: "sell", Method: "portfolio.sell", Required: []string{"symbol", "shares", "price", "reason"}, ReadOnly: false},
			"sync":         {Action: "sync", Method: "portfolio.sync_real", Required: []string{"symbol", "shares", "avg_cost"}, ReadOnly: false},
			"stops":        {Action: "stops", Method: "portfolio.update_stops", Required: []string{"symbol", "stop_loss"}, ReadOnly: false},
			"watch_add":    {Action: "watch_add", Method: "watch.add", Required: []string{"symbol"}, ReadOnly: false},
			"watch_remove": {Action: "watch_remove", Method: "watch.remove", Required: []string{"symbol"}, ReadOnly: false},
		},
	},
	{
		Name: "hapi_risk",
		Description: "Risk management desk — trap detection, intraday volume analysis, risk checks, and alert watchpoints. " +
			"Actions: trap, volume, risk, watchpoint_set, watchpoint_list, watchpoint_clear.",
		ReadOnly: false,
		Actions: map[string]facadeAction{
			"trap":             {Action: "trap", Method: "trap.detect", Required: []string{"symbol"}, ReadOnly: true},
			"volume":           {Action: "volume", Method: "intraday.volume_profile", Required: []string{"symbol"}, Defaults: map[string]any{"lookback": 80}, ReadOnly: true},
			"risk":             {Action: "risk", Method: "risk.check", Required: []string{"symbol"}, ReadOnly: true},
			"watchpoint_set":   {Action: "watchpoint_set", Method: "watchpoint.set", Required: []string{"symbol", "condition"}, ReadOnly: false},
			"watchpoint_list":  {Action: "watchpoint_list", Method: "watchpoint.list", ReadOnly: true},
			"watchpoint_clear": {Action: "watchpoint_clear", Method: "watchpoint.clear", ReadOnly: false},
		},
	},
	{
		Name: "hapi_research",
		Description: "Research desk — backtest and strategy evaluation. " +
			"Actions: evaluate, evolve, fund_manager, forensics_tag, promote_lesson, pattern, arena_stats, status, result, list.",
		ReadOnly: false, // mixed: status/result/list are read-only; submit actions write job artifacts
		Actions: map[string]facadeAction{
			"evaluate":       {Action: "evaluate", Method: "backtest.evaluate", ReadOnly: false},
			"evolve":         {Action: "evolve", Method: "backtest.evolve", ReadOnly: false},
			"fund_manager":   {Action: "fund_manager", Method: "backtest.fund_manager", Required: []string{"symbol"}, ReadOnly: false},
			"forensics_tag":  {Action: "forensics_tag", Method: "backtest.forensics_tag", Required: []string{"run_id"}, Defaults: map[string]any{"write_report": true}, ReadOnly: false},
			"promote_lesson": {Action: "promote_lesson", Method: "backtest.promote_lesson", Required: []string{"run_id"}, Defaults: map[string]any{"dry_run": true}, ReadOnly: false},
			"pattern":        {Action: "pattern", Method: "backtest.pattern_discriminator", ReadOnly: false},
			"arena_stats":    {Action: "arena_stats", Method: "arena.stats", ReadOnly: true},
			"status":         {Action: "status", Method: "backtest.status", Required: []string{"run_id"}, ReadOnly: true},
			"result":         {Action: "result", Method: "backtest.result", Required: []string{"run_id"}, ReadOnly: true},
			"list":           {Action: "list", Method: "backtest.list", ReadOnly: true},
		},
	},
	{
		Name: "hapi_memory",
		Description: "HAPI memory — finance-scoped search, recall, and save through hapi-edge only. " +
			"Actions: search, recall, save.",
		ReadOnly: false,
		Actions: map[string]facadeAction{
			"search": {Action: "search", Method: "hypertachi.search_memory", Required: []string{"query"}, ReadOnly: true},
			"recall": {Action: "recall", Method: "hypertachi.recall_context", Required: []string{"query"}, ReadOnly: true},
			"save":   {Action: "save", Method: "hypertachi.save_memory", Required: []string{"text"}, ReadOnly: false},
		},
	},
	{
		Name: "hapi_playbook",
		Description: "HAPI equity playbook — durable stock setups, execution rules, risk limits, and review templates. " +
			"Actions: search, browse, read, write.",
		ReadOnly: false,
		Actions: map[string]facadeAction{
			"search": {Action: "search", Method: "hypertachi.playbook_search", Required: []string{"query"}, ReadOnly: true},
			"browse": {Action: "browse", Method: "hypertachi.playbook_browse", ReadOnly: true},
			"read":   {Action: "read", Method: "hypertachi.playbook_read", Required: []string{"path"}, ReadOnly: true},
			"write":  {Action: "write", Method: "hypertachi.playbook_write", Required: []string{"title", "text"}, ReadOnly: false},
		},
	},
	{
		Name: "hapi_board",
		Description: "HAPI agent board — kanban cards that remind specific agents to pick up work. " +
			"Actions: inbox, post, update.",
		ReadOnly: false,
		Actions: map[string]facadeAction{
			"inbox":  {Action: "inbox", Method: "hypertachi.check_inbox", Required: []string{"agent_id"}, ReadOnly: true},
			"post":   {Action: "post", Method: "hypertachi.post_card", Required: []string{"to_agent", "title", "body"}, ReadOnly: false},
			"update": {Action: "update", Method: "hypertachi.update_card", Required: []string{"card_id", "new_status"}, ReadOnly: false},
		},
	},
}

// ── Facade handler generator ──────────────────────────────────

// facadeHandler returns a ToolHandler that dispatches to the correct RPC method
// or Tachi tool based on the `action` parameter.
func facadeHandler(spec facadeSpec, dispatcher RPCDispatcher) mcp.ToolHandler {
	return func(ctx context.Context, req *mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		params, err := arguments(req)
		if err != nil {
			return toolError(err), nil
		}

		// 1. Extract action
		actionName, _ := params["action"].(string)
		if actionName == "" {
			// default to first action (sorted for determinism)
			actionName = firstActionKey(spec.Actions)
		}
		delete(params, "action")

		// 2. Look up action
		action, ok := spec.Actions[actionName]
		if !ok {
			available := actionKeys(spec.Actions)
			return toolError(fmt.Errorf("unknown action %q for %s; available: %s", actionName, spec.Name, strings.Join(available, ", "))), nil
		}

		// 3. Apply defaults
		for key, value := range action.Defaults {
			if _, exists := params[key]; !exists {
				params[key] = value
			}
		}
		normalizeMCPParams(params)

		// 3b. Fallback: if action is "peers" and "query" is empty but "symbol" is provided, copy symbol to query.
		if spec.Name == "hapi_scanner" && actionName == "peers" {
			if q, _ := params["query"].(string); strings.TrimSpace(q) == "" {
				if sym, ok := params["symbol"].(string); ok && strings.TrimSpace(sym) != "" {
					params["query"] = sym
				}
			}
		}
		if spec.Name == "hapi_scanner" && actionName == "discover" {
			if facadeBool(params["persist"]) || facadeBool(params["write_cache"]) {
				return toolError(fmt.Errorf("hapi_scanner/discover is read-only; use discovery_scan when you need persist=true artifact writes")), nil
			}
		}

		// 4. Validate required params
		if err := requireParams(spec.Name+"/"+actionName, params, action.Required); err != nil {
			return toolError(fmt.Errorf("action %s: %w", actionName, err)), nil
		}

		// 5. Route snapshot actions explicitly: core by default, Python only when requested.
		method := action.Method
		if spec.Name == "hapi_analyst" && (actionName == "snapshot" || actionName == "batch") {
			source := ""
			if rawSource, exists := params["snapshot_source"]; exists && rawSource != nil {
				source = strings.ToLower(strings.TrimSpace(fmt.Sprint(rawSource)))
			}
			switch source {
			case "", "core", "snapshot.core", "go", "go_core":
				if source != "" || useCoreSnapshotDefault() {
					if actionName == "snapshot" {
						method = "snapshot.core"
					} else {
						method = "snapshot.core_batch"
					}
				} else if actionName == "snapshot" {
					method = "snapshot.ls1"
				} else {
					method = "snapshot.batch"
				}
			case "python", "ls1", "snapshot.ls1", "python_full", "snapshot.python_full":
				if actionName == "snapshot" {
					method = "snapshot.ls1"
				} else {
					method = "snapshot.batch"
				}
			default:
				return toolError(fmt.Errorf("snapshot_source must be core or python")), nil
			}
			if _, exists := params["format"]; !exists {
				params["format"] = snapshotDefaultFormat(method)
			}
		}
		if spec.Name == "hapi_market" && actionName == "intel" {
			if _, hasSymbol := params["symbol"]; hasSymbol {
				method = "intel.stock"
			}
		}

		// 6. Dispatch
		var value any
		if isHyperTachiMethod(method) {
			// Delegate to Tachi MCP
			tachiTool := tachiToolName(method)
			// Apply Tachi-specific defaults based on the facade action
			tachiDefaults := tachiActionDefaults(spec.Name, actionName)
			for key, val := range tachiDefaults {
				if _, exists := params[key]; !exists {
					params[key] = val
				}
			}
			call, err := callHyperionMemoryTool(ctx, tachiTool, params)
			if err != nil {
				return toolError(err), nil
			}
			value = map[string]any{
				"facade":        spec.Name,
				"action":        actionName,
				"memory_tool":   tachiTool,
				"memory_result": summarizeHyperTachiResult(call),
			}
		} else {
			// Standard RPC dispatch
			if isSnapshotMethod(method) {
				if err := validateSnapshotParams(method, params); err != nil {
					return toolError(err), nil
				}
			}
			dispatchResult, err := dispatcher.Dispatch(ctx, method, params)
			if err != nil {
				return toolError(err), nil
			}
			value = dispatchResult
		}

		return result(value), nil
	}
}

// ── Facade → toolSpec conversion ──────────────────────────────

func facadeToolSpecs(dispatcher RPCDispatcher) []toolSpec {
	specs := make([]toolSpec, 0, len(facadeSpecs))
	for _, fs := range facadeSpecs {
		specs = append(specs, facadeSpecToToolSpec(fs, dispatcher))
	}
	return specs
}

func facadeSpecToToolSpec(fs facadeSpec, dispatcher RPCDispatcher) toolSpec {
	// Build properties: action + union of all action params
	props := map[string]any{
		"action": enumStringProp(
			fmt.Sprintf("Action to execute. Available: %s.", strings.Join(actionKeys(fs.Actions), ", ")),
			actionKeys(fs.Actions),
		),
	}
	for key, value := range facadeSharedProperties(fs.Name) {
		props[key] = value
	}

	// Build description with action listing
	desc := fs.Description

	return toolSpec{
		name:        fs.Name,
		description: desc,
		properties:  props,
		required:    []string{"action"},
		readOnly:    fs.ReadOnly,
		handler:     facadeHandler(fs, dispatcher),
	}
}

// ── Helpers ───────────────────────────────────────────────────

func firstActionKey(actions map[string]facadeAction) string {
	keys := actionKeys(actions)
	if len(keys) == 0 {
		return ""
	}
	return keys[0]
}

func actionKeys(actions map[string]facadeAction) []string {
	keys := make([]string, 0, len(actions))
	for k := range actions {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func facadeBool(value any) bool {
	switch typed := value.(type) {
	case bool:
		return typed
	case string:
		switch strings.ToLower(strings.TrimSpace(typed)) {
		case "1", "true", "yes", "on":
			return true
		}
	}
	return false
}

func isHyperTachiMethod(method string) bool {
	return strings.HasPrefix(method, "hypertachi.")
}

func tachiToolName(method string) string {
	// "hypertachi.search_memory" → "search_memory"
	return strings.TrimPrefix(method, "hypertachi.")
}

// tachiActionDefaults returns default params for Tachi actions
// when invoked through a facade (so the caller doesn't need to know them).
func tachiActionDefaults(facadeName, actionName string) map[string]any {
	switch {
	case facadeName == "hapi_memory" && actionName == "search":
		return hapiMemoryRetrievalDefaults()
	case facadeName == "hapi_memory" && actionName == "recall":
		return hapiMemoryRetrievalDefaults()
	case facadeName == "hapi_memory" && actionName == "graph":
		return map[string]any{"top_k": 3, "depth": 1, "domain": "equity_trading"}
	case facadeName == "hapi_memory" && actionName == "save":
		return map[string]any{"scope": "project", "domain": "equity_trading"}
	case facadeName == "hapi_playbook" && actionName == "search":
		return map[string]any{"scope": "playbook", "domain": "equity_trading"}
	case facadeName == "hapi_playbook" && actionName == "write":
		return map[string]any{"kind": "playbook", "scope": "global", "domain": "equity_trading", "force": true}
	case facadeName == "hapi_board" && actionName == "inbox":
		return map[string]any{"agent_id": "hapi", "include_broadcast": true, "limit": 20}
	case facadeName == "hapi_board" && actionName == "post":
		return map[string]any{"from_agent": "hapi", "priority": "medium", "card_type": "request"}
	default:
		return nil
	}
}

func hapiMemoryRetrievalDefaults() map[string]any {
	defaults := map[string]any{"top_k": 6, "domain": "equity_trading"}
	if prefix := marketClockMemoryPathPrefix(tachiClockNow()); prefix != "" {
		defaults["path_prefix"] = prefix
		defaults["market_clock_router"] = true
	}
	return defaults
}

func marketClockMemoryPathPrefix(now time.Time) string {
	loc := getShanghaiLocation()
	local := now.In(loc)
	if local.Weekday() == time.Saturday || local.Weekday() == time.Sunday {
		return "/trading/equity/daily_review"
	}
	minutes := local.Hour()*60 + local.Minute()
	switch {
	case minutes >= 9*60+15 && minutes < 10*60:
		return "/trading/equity/ops/T0"
	case minutes >= 9*60+15 && minutes < 15*60:
		return "/trading/equity/journal/positions"
	case minutes >= 15*60:
		return "/trading/equity/daily_review"
	default:
		return ""
	}
}

func facadeSharedProperties(name string) map[string]any {
	switch name {
	case "hapi_market":
		return map[string]any{
			"symbol":     stringProp("A-share symbol, e.g. 300502.SZ. Required for actions quote/klines/flow."),
			"symbols":    arrayOrStringProp("A-share symbols array or comma string. Required for action=quote_batch."),
			"timeout_ms": timeoutMSProp("Optional Rust UDS probe deadline in milliseconds for cold cache refresh."),
			"period":     stringProp("K-line period: day, 15m, 60m, 5m, 1m (action=klines)"),
			"count":      numberProp("Number of K-line bars (action=klines)"),
			"dataset":    stringProp("Exact intel_cache dataset key (action=intel)"),
			"trade_date": stringProp("Optional trade date for intel (action=intel)"),
		}
	case "hapi_scanner":
		return map[string]any{
			"symbol":      stringProp("Optional target symbol for profile/peers context"),
			"query":       stringProp("Peer query symbol/name (action=peers); substring filter (action=symbols)"),
			"top_n":       numberProp("Maximum peers/symbols to return"),
			"persist":     boolProp("Persist official discovery_results.json for action=discover; default false"),
			"write_cache": boolProp("Alias for persist on action=discover; default false"),
			"layer":       stringProp("Filter by symbols layer (action=symbols)"),
			"category":    stringProp("Filter by symbols category (action=symbols)"),
			"limit":       numberProp("Max rows to return"),
			"fields":      arrayOrStringProp("Field projection (action=symbols): 'compact' or 'all'"),
			"mode":        enumStringProp("Discovery mode (action=discover)", []string{"chan", "shortterm", "breakout", "gap", "all"}),
			"universe":    enumStringProp("Discovery universe (action=discover)", []string{"watchlist", "a_hot_100"}),
			"date":        stringProp("Optional trading date for action=profile"),
			"latest":      boolProp("Return only the latest row (action=profile)"),
		}
	case "hapi_analyst":
		return map[string]any{
			"symbol": stringProp("A-share symbol, e.g. 300502.SZ. Required for actions triage/snapshot/core/analyze."),
			"symbols": arrayOrStringProp(
				"A-share symbols array or comma string. Required for action=batch/core_batch/parity.",
			),
			"name":       stringProp("Optional stock display name"),
			"fields":     arrayOrStringProp("Field projection: array or preset thin/core/hunt/guard/micro. format=json requires fields."),
			"format":     enumStringProp("Output format. json with fields/presets for structured extraction, raw for full payload, markdown for Go-rendered reports.", []string{"brief", "markdown", "json", "raw", "compact", "lean"}),
			"timeout_ms": timeoutMSProp("Optional deadline for Go/Rust snapshot paths; defaults to 5000."),
			"snapshot_source": enumStringProp(
				"Snapshot source for action=snapshot/batch/analyze/triage. Default core; python forces LS1 oracle.",
				[]string{"python", "core"},
			),
			"core":         boolProp("Force Go/Rust snapshot.core for triage/analyze when core-default env is disabled"),
			"include_trap": boolProp("Include trap detection output"),
			"focus":        arrayOrStringProp("Optional markdown focus sections: chan, volume_15m, traps, gap, compression, ichimoku, risk"),
			"snapshot_id":  stringProp("snapshot_id returned by triage (for layer-2 deep_dive, use standalone hapi_deep_dive tool)"),
		}
	case "hapi_portfolio":
		return map[string]any{
			"portfolio": stringProp("Portfolio name: shadow or real (action=positions/summary)"),
			"symbol":    stringProp("A-share symbol (action=watchlist_add/watchlist_remove, required)"),
			"date":      stringProp("Trading date, e.g. 2026-05-26 (action=daily)"),
			"limit":     numberProp("Max rows (action=journal/trades/watchlist)"),
			"offset":    numberProp("Pagination offset (action=journal/trades/watchlist)"),
			"category":  stringProp("Watchlist category filter (action=watchlist/watchlist_add)"),
			"notes":     stringProp("Notes (action=watchlist_add)"),
			"ttl":       numberProp("Prune TTL days (action=watchlist_prune)"),
			"dry_run":   boolProp("Preview without deleting (action=watchlist_prune)"),
			"fields":    arrayOrStringProp("Field projection: 'compact' or 'all' (action=journal/trades)"),
		}
	case "hapi_trade":
		return map[string]any{
			"symbol":      stringProp("A-share symbol, e.g. 300502.SZ. Required for all actions."),
			"name":        stringProp("Optional stock display name"),
			"shares":      numberProp("Number of shares (action=buy/sell/sync). Must be 100-lot multiples for A-share."),
			"price":       numberProp("Execution price per share (action=buy/sell)"),
			"avg_cost":    numberProp("Average cost for sync (action=sync)"),
			"reason":      stringProp("Trade rationale (action=buy/sell, required)"),
			"stop_loss":   numberProp("Stop-loss price (action=stops, required)"),
			"take_profit": numberProp("Take-profit price (action=stops)"),
		}
	case "hapi_risk":
		return map[string]any{
			"symbol":      stringProp("A-share symbol. Required for trap/volume/risk/watchpoint_set."),
			"name":        stringProp("Optional stock display name"),
			"lookback":    numberProp("Lookback bars (action=trap/volume)"),
			"condition":   stringProp("Signal condition, e.g. crash_signal, trap_detection, * (action=watchpoint_set, required)"),
			"severity":    enumStringProp("Watchpoint severity (action=watchpoint_set)", []string{"info", "warning", "critical"}),
			"id":          numberProp("Watchpoint id (action=watchpoint_clear)"),
			"active_only": boolProp("Only list active watchpoints (action=watchpoint_list)"),
		}
	case "hapi_memory":
		return map[string]any{
			"query":       stringProp("Search/recall query text (action=search/recall)"),
			"text":        stringProp("Full text content (action=save, required)"),
			"top_k":       numberProp("Number of results (action=search/recall)"),
			"path_prefix": stringProp("Path prefix filter (action=search/recall)"),
			"category":    stringProp("Memory category (action=save)"),
			"keywords":    arrayOrStringProp("Keyword tags (action=save)"),
			"importance":  numberProp("Importance score 0.0-1.0 (action=save)"),
			"domain":      stringProp("Domain filter, default equity_trading (action=search/recall/save)"),
		}
	case "hapi_playbook":
		return map[string]any{
			"query":    stringProp("Playbook search query (action=search)"),
			"title":    stringProp("Playbook title (action=write, required)"),
			"text":     stringProp("Playbook body (action=write, required)"),
			"path":     stringProp("Optional playbook path under /wiki/... storage compatibility"),
			"category": stringProp("Playbook category, e.g. entry, defense, risk, review"),
			"keywords": arrayOrStringProp("Playbook tags"),
			"entities": arrayOrStringProp("Related symbols, sectors, or systems"),
			"top_k":    numberProp("Number of playbook hits (action=search)"),
			"domain":   stringProp("Domain filter, default equity_trading"),
		}
	case "hapi_research":
		return map[string]any{
			"symbol":       stringProp("A-share symbol (action=fund_manager, required)"),
			"run_id":       stringProp("Backtest run_id (action=forensics_tag/promote_lesson/status/result, required)"),
			"rounds":       numberProp("Evolution rounds (action=evolve)"),
			"dry_run":      boolProp("Preview without writes (action=evolve/promote_lesson)"),
			"days":         numberProp("Historical days (action=evaluate)"),
			"max_days":     numberProp("Max trading days (action=fund_manager)"),
			"model":        stringProp("LLM backend (action=evolve)"),
			"write_report": boolProp("Write forensic report (action=forensics_tag)"),
		}
	case "hapi_board":
		return map[string]any{
			"agent_id":          stringProp("Receiving agent ID (action=inbox, required)"),
			"from_agent":        stringProp("Sending agent ID (action=post; default hapi)"),
			"to_agent":          stringProp("Target agent ID or * for broadcast (action=post, required)"),
			"title":             stringProp("Card title (action=post, required unless summary provided via backend)"),
			"body":              stringProp("Card body (action=post, required unless summary provided via backend)"),
			"summary":           stringProp("Short summary used to compose a post card (backend alias)"),
			"priority":          enumStringProp("Card priority (action=post)", []string{"low", "medium", "high", "critical"}),
			"card_type":         enumStringProp("Card type (action=post)", []string{"request", "task", "alert", "review"}),
			"card_id":           stringProp("Kanban card ID (action=update, required)"),
			"new_status":        enumStringProp("New card status (action=update, required)", []string{"open", "acknowledged", "resolved", "expired"}),
			"response_text":     stringProp("Optional reply appended when updating a card (action=update)"),
			"status_filter":     stringProp("Optional inbox status filter (action=inbox)"),
			"include_broadcast": boolProp("Include broadcast cards addressed to * (action=inbox)"),
			"limit":             numberProp("Maximum cards returned (action=inbox)"),
		}
	default:
		return nil
	}
}
