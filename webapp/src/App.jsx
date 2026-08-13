import { Routes, Route } from 'react-router-dom'
import Header from './components/Header'
import Dashboard from './pages/Dashboard'
import StockScreen from './pages/StockScreen'
import OptionsScreen from './pages/OptionsScreen'
import PrivateCompaniesScreen from './pages/PrivateCompaniesScreen'
import TickerDetail from './pages/TickerDetail'
import StockTeam from './pages/StockTeam'
import ResearchChat from './pages/ResearchChat'
import StockComparison from './pages/StockComparison'
import Login from './pages/Login'
import Signup from './pages/Signup'
import Brokerage from './pages/Brokerage'
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
              <Route path="/tickers/:ticker" element={<TickerDetail />} />
              <Route path="/tickers/:ticker/team" element={<StockTeam />} />
              <Route path="/research/stock-comparison" element={<StockComparison />} />
              <Route path="/chat" element={<ResearchChat />} />
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
