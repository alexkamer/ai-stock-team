import { Routes, Route } from 'react-router-dom'
import Header from './components/Header'
import Dashboard from './pages/Dashboard'
import TickerDetail from './pages/TickerDetail'
import StockTeam from './pages/StockTeam'
import ResearchChat from './pages/ResearchChat'

export default function App() {
  return (
    <>
      <Header />
      <main className="page">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/tickers/:ticker" element={<TickerDetail />} />
          <Route path="/tickers/:ticker/team" element={<StockTeam />} />
          <Route path="/chat" element={<ResearchChat />} />
        </Routes>
      </main>
    </>
  )
}
