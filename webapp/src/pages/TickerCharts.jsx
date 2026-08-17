import { useEffect, useState } from 'react'
import { Link, useOutletContext, useParams } from 'react-router-dom'
import { getJSON } from '../api/client'
import PriceChart from '../components/PriceChart'

const CHART_PREFS_KEY = 'ticker-chart-prefs'

function loadChartPrefs() {
  try {
    const raw = localStorage.getItem(CHART_PREFS_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function saveChartPrefs(prefs) {
  try {
    localStorage.setItem(CHART_PREFS_KEY, JSON.stringify(prefs))
  } catch {
    // localStorage unavailable (private browsing, quota) - preference just won't persist
  }
}

export default function TickerCharts() {
  const { ticker } = useParams()
  const { positive, previousClose } = useOutletContext()
  const [chartPrefs] = useState(loadChartPrefs)
  const [period, setPeriod] = useState(chartPrefs.period ?? '1mo')
  const [prices, setPrices] = useState(null)
  const [labels, setLabels] = useState(null)
  const [volumes, setVolumes] = useState(null)
  const [highs, setHighs] = useState(null)
  const [lows, setLows] = useState(null)
  const [opens, setOpens] = useState(null)
  const [isRegularHours, setIsRegularHours] = useState(null)
  const [benchmarkPrices, setBenchmarkPrices] = useState(null)
  const [compareBenchmark, setCompareBenchmark] = useState(chartPrefs.compareBenchmark ?? false)
  const [chartType, setChartType] = useState(chartPrefs.chartType ?? 'line')
  const [extendedHours, setExtendedHours] = useState(chartPrefs.extendedHours ?? false)
  const [chartLoading, setChartLoading] = useState(false)

  useEffect(() => {
    setPrices(null)
    setLabels(null)
    setVolumes(null)
    setHighs(null)
    setLows(null)
    setOpens(null)
    setIsRegularHours(null)
    setBenchmarkPrices(null)
  }, [ticker])

  useEffect(() => {
    let cancelled = false
    setChartLoading(true)
    const benchmarkParam = compareBenchmark ? '&benchmark=SPY' : ''
    getJSON(`/tickers/${ticker}/history?period=${period}${benchmarkParam}`)
      .then((data) => {
        if (cancelled) return
        setPrices(data.prices)
        setLabels(data.labels)
        setVolumes(data.volumes ?? null)
        setHighs(data.highs ?? null)
        setLows(data.lows ?? null)
        setOpens(data.opens ?? null)
        setIsRegularHours(data.is_regular_hours ?? null)
        setBenchmarkPrices(data.benchmark_prices ?? null)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setChartLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ticker, period, compareBenchmark])

  useEffect(() => {
    saveChartPrefs({ period, compareBenchmark, chartType, extendedHours })
  }, [period, compareBenchmark, chartType, extendedHours])

  return (
    <div className="card">
      <div className="ticker-detail__chart-card-head">
        <Link to={`/research/advanced-charts?symbol=${ticker}`} className="ticker-detail__advanced-chart-link">
          Open in Advanced Charts →
        </Link>
      </div>
      <PriceChart
        ticker={ticker}
        prices={prices}
        labels={labels}
        volumes={volumes}
        opens={opens}
        highs={highs}
        lows={lows}
        period={period}
        onPeriodChange={setPeriod}
        positive={positive}
        previousClose={previousClose}
        loading={chartLoading}
        isRegularHours={isRegularHours}
        benchmarkPrices={benchmarkPrices}
        benchmarkLabel="S&P 500"
        compareEnabled={compareBenchmark}
        onToggleCompare={() => setCompareBenchmark((v) => !v)}
        chartType={chartType}
        onChartTypeChange={setChartType}
        extendedHours={extendedHours}
        onToggleExtendedHours={() => setExtendedHours((v) => !v)}
      />
    </div>
  )
}
