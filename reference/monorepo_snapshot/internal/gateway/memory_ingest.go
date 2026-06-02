package gateway

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"hyperion/internal/portfolio"
)

const portfolioMemoryToolTimeout = 3 * time.Second

func (s *Server) publishPortfolioTradeMemory(ctx context.Context, portfolioName string, result portfolio.TradeResult, params map[string]any) {
	if strings.ToLower(strings.TrimSpace(portfolioName)) != "real" || result.Status != "ok" {
		return
	}
	symbol := strings.ToUpper(strings.TrimSpace(result.Symbol))
	if symbol == "" {
		return
	}
	action := strings.ToLower(strings.TrimSpace(result.Action))
	if action == "" {
		action = "trade"
	}
	now := time.Now().In(shanghaiLocation())
	summary := fmt.Sprintf("[实盘%s] %s %d股 @ %.3f", strings.ToUpper(action), symbol, result.Shares, result.Price)
	payload := map[string]any{
		"event":     "portfolio_trade",
		"portfolio": portfolioName,
		"result":    result,
		"params":    params,
		"as_of":     now.Format(time.RFC3339),
	}
	s.publishOperationalMemory(ctx, operationalMemoryPayload{
		Summary:    summary,
		TextTitle:  summary,
		Path:       fmt.Sprintf("/trading/equity/journal/positions/%s/%s/%s-%d", symbol, now.Format("2006-01-02"), action, now.UnixNano()),
		Topic:      "real_position_trade",
		Keywords:   []string{"real_position", "trade", action, symbol},
		Entities:   []string{symbol},
		Importance: 0.78,
		Source:     "hapi-edge.portfolio_rpc",
		Metadata:   payload,
	})
}

func (s *Server) publishPortfolioSyncMemory(ctx context.Context, symbol, name string, shares int, avgCost, stopLoss, takeProfit float64) {
	symbol = strings.ToUpper(strings.TrimSpace(symbol))
	if symbol == "" {
		return
	}
	now := time.Now().In(shanghaiLocation())
	state := "synced"
	if shares <= 0 {
		state = "cleared"
	}
	summary := fmt.Sprintf("[实盘同步] %s %s shares=%d avg_cost=%.3f", symbol, state, shares, avgCost)
	payload := map[string]any{
		"event":       "real_position_sync",
		"symbol":      symbol,
		"name":        strings.TrimSpace(name),
		"shares":      shares,
		"avg_cost":    avgCost,
		"stop_loss":   stopLoss,
		"take_profit": takeProfit,
		"state":       state,
		"as_of":       now.Format(time.RFC3339),
	}
	s.publishOperationalMemory(ctx, operationalMemoryPayload{
		Summary:    summary,
		TextTitle:  summary,
		Path:       fmt.Sprintf("/trading/equity/journal/positions/%s/%s/sync-%d", symbol, now.Format("2006-01-02"), now.UnixNano()),
		Topic:      "real_position_sync",
		Keywords:   []string{"real_position", "sync", state, symbol},
		Entities:   []string{symbol},
		Importance: 0.74,
		Source:     "hapi-edge.portfolio_sync_real",
		Metadata:   payload,
	})
}

func (s *Server) publishDailySummaryMemory(ctx context.Context, summary map[string]any) {
	if summary == nil || boolParam(summary["available"], true) == false {
		return
	}
	date := strings.TrimSpace(stringValue(summary["date"]))
	if date == "" {
		date = time.Now().In(shanghaiLocation()).Format("2006-01-02")
	}
	title := fmt.Sprintf("[盘后总结] %s", date)
	s.publishOperationalMemory(ctx, operationalMemoryPayload{
		Summary:    title,
		TextTitle:  title,
		Path:       fmt.Sprintf("/trading/equity/daily_review/%s", date),
		Topic:      "daily_review",
		Keywords:   []string{"daily_review", "post_market", date},
		Entities:   []string{},
		Importance: 0.72,
		Source:     "hapi-edge.daily_summary",
		Metadata: map[string]any{
			"event":   "daily_summary",
			"date":    date,
			"summary": summary,
		},
	})
}

type operationalMemoryPayload struct {
	Summary    string
	TextTitle  string
	Path       string
	Topic      string
	Keywords   []string
	Entities   []string
	Importance float64
	Source     string
	Metadata   map[string]any
}

func (s *Server) publishOperationalMemory(ctx context.Context, payload operationalMemoryPayload) {
	raw, err := json.MarshalIndent(payload.Metadata, "", "  ")
	if err != nil {
		log.Printf("operational memory marshal failed: %v", err)
		return
	}
	text := fmt.Sprintf(`# %s

%s
`, payload.TextTitle, string(raw))
	args := map[string]any{
		"text":             text,
		"summary":          payload.Summary,
		"path":             payload.Path,
		"importance":       payload.Importance,
		"category":         "fact",
		"topic":            payload.Topic,
		"keywords":         payload.Keywords,
		"entities":         payload.Entities,
		"scope":            "project",
		"domain":           "equity_trading",
		"source":           payload.Source,
		"retention_policy": "durable",
		"force":            true,
		"metadata":         payload.Metadata,
	}
	if err := s.callMemoryTool(ctx, "hapi_save", fmt.Sprintf("%s-%d", payload.Topic, time.Now().UnixNano()), args, portfolioMemoryToolTimeout); err != nil {
		log.Printf("operational memory publish failed (%s): %v", payload.Topic, err)
	}
}
