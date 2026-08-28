import { Routes, Route } from 'react-router-dom'
import Header from './components/Header'
import Dashboard from './pages/Dashboard'
import StockScreen from './pages/StockScreen'
import OptionsScreen from './pages/OptionsScreen'
import PrivateCompaniesScreen from './pages/PrivateCompaniesScreen'
import TickerDetail from './pages/TickerDetail'
import TickerOverview from './pages/TickerOverview'
import TickerCharts from './pages/TickerCharts'
import TickerNews from './pages/TickerNews'
import StockTeam from './pages/StockTeam'
import Scan from './pages/Scan'
import ResearchChat from './pages/ResearchChat'
import StockComparison from './pages/StockComparison'
import AdvancedCharts from './pages/AdvancedCharts'
import Login from './pages/Login'
import Signup from './pages/Signup'
import Brokerage from './pages/Brokerage'
import TrackRecord from './pages/TrackRecord'
import RequireAuth from './components/RequireAuth'
import { AuthProvider } from './context/AuthContext'
import { ResearchChatProvider } from './context/ResearchChatContext'
import { WatchlistProvider } from './context/WatchlistContext'

export default function App() {
  return (
    <AuthProvider>
      <WatchlistProvider>
        <ResearchChatProvider>
          <Header />
          <main className="page">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/markets/stocks/:screen" element={<StockScreen />} />
              <Route path="/markets/options/:screen" element={<OptionsScreen />} />
              <Route path="/markets/private-companies" element={<PrivateCompaniesScreen />} />
              <Route path="/tickers/:ticker" element={<TickerDetail />}>
                <Route index element={<TickerOverview />} />
                <Route path="charts" element={<TickerCharts />} />
                <Route path="news" element={<TickerNews />} />
                <Route path="team" element={<StockTeam />} />
              </Route>
              <Route path="/scan" element={<Scan />} />
              <Route path="/research/stock-comparison" element={<StockComparison />} />
              <Route path="/research/advanced-charts" element={<AdvancedCharts />} />
              <Route path="/chat" element={<ResearchChat />} />
              <Route path="/track-record" element={<TrackRecord />} />
              <Route path="/login" element={<Login />} />
              <Route path="/signup" element={<Signup />} />
              <Route
                path="/brokerage"
                element={
                  <RequireAuth>
                    <Brokerage />
                  </RequireAuth>
                }
              />
            </Routes>
          </main>
        </ResearchChatProvider>
      </WatchlistProvider>
    </AuthProvider>
  )
}
