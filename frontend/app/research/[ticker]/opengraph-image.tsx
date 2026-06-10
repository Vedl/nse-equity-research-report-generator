import { ImageResponse } from "next/og"
import { fetchResearch, normaliseTicker } from "@/lib/api"
import { fmtINR, fmtPct } from "@/lib/formatters"
import { calcUpside } from "@/lib/dcf"

export const size = { width: 1200, height: 630 }
export const contentType = "image/png"
export const alt = "Equity Research Report"

export default async function OGImage({
  params,
}: {
  params: { ticker: string }
}) {
  const ticker = normaliseTicker(params.ticker)
  const base = ticker.replace(".NS", "")

  let name = base
  let price = "—"
  let sector = ""
  let dcfLabel = ""
  let upside = ""
  let upsideColor = "#94a3b8"

  try {
    const data = await fetchResearch(ticker)
    name = data.company.name ?? base
    price = data.price.current ? fmtINR(data.price.current) : "—"
    sector = data.company.sector ?? ""
    const dcfVal = data.valuation.dcf?.intrinsic_value
    if (dcfVal != null) {
      dcfLabel = `DCF ${fmtINR(dcfVal)}`
      const up = calcUpside(dcfVal, data.price.current)
      if (up != null) {
        upside = `${up >= 0 ? "+" : ""}${fmtPct(up)}`
        upsideColor = up >= 0 ? "#10b981" : "#ef4444"
      }
    }
  } catch {
    // Fallback to ticker name on error
  }

  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          width: "100%",
          height: "100%",
          background: "#09090b",
          padding: "60px 72px",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        {/* Top: branding */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div
            style={{
              width: "36px",
              height: "36px",
              background: "#0ea5e9",
              borderRadius: "8px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <span style={{ color: "white", fontSize: "20px", fontWeight: 700 }}>
              ER
            </span>
          </div>
          <span style={{ color: "#64748b", fontSize: "18px" }}>
            Equity Research
          </span>
        </div>

        {/* Middle: company info */}
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <span
              style={{
                fontFamily: "monospace",
                color: "#0ea5e9",
                fontSize: "22px",
                fontWeight: 700,
                letterSpacing: "0.05em",
              }}
            >
              {base}
            </span>
            {sector && (
              <span
                style={{
                  background: "#0ea5e920",
                  border: "1px solid #0ea5e940",
                  color: "#38bdf8",
                  fontSize: "14px",
                  padding: "4px 12px",
                  borderRadius: "100px",
                }}
              >
                {sector}
              </span>
            )}
          </div>
          <h1
            style={{
              color: "#f1f5f9",
              fontSize: "48px",
              fontWeight: 800,
              lineHeight: 1.1,
              margin: 0,
              maxWidth: "800px",
            }}
          >
            {name}
          </h1>
        </div>

        {/* Bottom: metrics */}
        <div style={{ display: "flex", gap: "48px" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
            <span style={{ color: "#64748b", fontSize: "14px" }}>
              Current Price
            </span>
            <span
              style={{
                color: "#f1f5f9",
                fontSize: "28px",
                fontWeight: 700,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {price}
            </span>
          </div>
          {dcfLabel && (
            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <span style={{ color: "#64748b", fontSize: "14px" }}>
                DCF Intrinsic Value
              </span>
              <span
                style={{
                  color: "#f1f5f9",
                  fontSize: "28px",
                  fontWeight: 700,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {dcfLabel.replace("DCF ", "")}
              </span>
            </div>
          )}
          {upside && (
            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <span style={{ color: "#64748b", fontSize: "14px" }}>
                Upside / Downside
              </span>
              <span
                style={{
                  color: upsideColor,
                  fontSize: "28px",
                  fontWeight: 700,
                }}
              >
                {upside}
              </span>
            </div>
          )}
        </div>
      </div>
    ),
    { ...size }
  )
}
