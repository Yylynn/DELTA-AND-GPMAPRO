export type Market = "A" | "HK" | "US";

const SH_PREFIXES = new Set(["600", "601", "603", "605", "688", "510", "511", "512", "513", "515", "516", "517", "518", "560", "561", "563", "588"]);
const SZ_PREFIXES = new Set(["000", "001", "002", "003", "300", "301", "159"]);
const QUALIFIED_CODE = /^(US|HK|SH|SZ)\.[A-Z0-9._-]+$/;

export class MarketCodeError extends Error {}

/** Convert a UI entry into the market-qualified Futu code used everywhere else. */
export function resolveMarketCode(input: string, market: Market): string {
  const value = input.trim().toUpperCase();
  if (!value) throw new MarketCodeError("请输入股票或 ETF 代码");
  if (value.includes(".")) {
    if (!QUALIFIED_CODE.test(value)) throw new MarketCodeError("请输入有效的富途代码，例如 SH.600519、SZ.000001、HK.00700 或 US.AAPL");
    return value;
  }
  if (market === "US") {
    if (!/^[A-Z0-9_-]+$/.test(value)) throw new MarketCodeError("美股代码格式无效");
    return `US.${value}`;
  }
  if (market === "HK") {
    if (!/^\d{1,5}$/.test(value)) throw new MarketCodeError("港股代码应为 1 至 5 位数字，或输入完整富途代码");
    return `HK.${value.padStart(5, "0")}`;
  }
  if (!/^\d{6}$/.test(value)) throw new MarketCodeError("A 股代码应为 6 位数字，或输入完整富途代码");
  const prefix = value.slice(0, 3);
  if (SH_PREFIXES.has(prefix)) return `SH.${value}`;
  if (SZ_PREFIXES.has(prefix)) return `SZ.${value}`;
  throw new MarketCodeError("无法根据该 A 股代码判断沪深交易所，请输入完整富途代码（例如 SH.600519）");
}

export function resolveMarketCodes(input: string, market: Market): { codes: string[]; error?: string } {
  const values = input.split(/[\s,]+/).filter(Boolean);
  if (!values.length) return { codes: [], error: "请输入至少一个代码" };
  try {
    return { codes: values.map(value => resolveMarketCode(value, market)) };
  } catch (error) {
    return { codes: [], error: error instanceof Error ? error.message : String(error) };
  }
}
