import type { Market } from "@/lib/marketCode";

type Props = {
  market: Market;
  value: string;
  onMarketChange: (market: Market) => void;
  onValueChange: (value: string) => void;
  className?: string;
};

export function MarketCodeInput({ market, value, onMarketChange, onValueChange, className = "" }: Props) {
  return <>
    <select className="terminal-input" value={market} onChange={event => onMarketChange(event.target.value as Market)} aria-label="市场">
      <option value="A">A 股</option>
      <option value="HK">港股</option>
      <option value="US">美股</option>
    </select>
    <input className={`terminal-input ${className}`} value={value} onChange={event => onValueChange(event.target.value.toUpperCase())} placeholder="600519 / 00700 / VXN" aria-label="股票代码" />
  </>;
}
