"""Theme catalog for the Themes tab - a fixed, curated list of themes
rather than free-text/AI-invented ones, so the basket behind each theme is
predictable and reviewable (same spirit as NEWS_CATEGORY_TICKERS in
tools.py, just richer: a description + risk label alongside the tickers).

Each theme's *ticker universe* (get_theme_universe below), though, is not
always the static list in this file - themes that map cleanly to one
yfinance industry classification (source="industry") get their tickers
from a live screen instead, so the universe reflects the real market
(current constituents, current market caps) rather than a list I hand-
picked from memory - which is exactly how CYBR (delisted after Palo Alto's
acquisition of CyberArk) ended up stale in the first shipped version.
Themes that genuinely span multiple industries either keep a curated
list (source="seed") or, for the ones tried with agents/theme_filings_
scorer.py, get their universe from an LLM's relevance scoring of live
SEC EDGAR full-text search hits (source="filings") - `tickers` on a
filings-sourced theme is kept as the fallback used before the scorer's
ever been run for it, or if a run turned up nothing.
"""

from time import monotonic

from core.db import SessionLocal
from core.models_db import ThemeFilingsPick
from core.tools import get_stock_price, parallel_map, screen_by_industry

THEME_CATALOG = [
    {
        "key": "ai-machine-learning",
        "name": "AI & Machine Learning",
        "description": "Companies building the chips, cloud infrastructure, and software powering the AI boom.",
        "about": "Artificial intelligence and machine learning refer to software that learns patterns from data rather than following hand-written rules - the technology behind large language models, image recognition, and the recommendation engines running underneath most consumer apps. This theme covers the full stack: the GPUs and custom chips that train and run these models, the cloud platforms that rent out that compute, and the software companies building AI directly into their products.\n\nDemand for AI compute has driven some of the largest capital-spending increases in corporate history, and companies in this theme have been direct beneficiaries. But that spending is concentrated among a small number of buyers, so a slowdown in any one of their budgets could ripple through the whole group. Much of the expected growth is also already reflected in these companies' valuations, and a technology this fast-moving carries real risk that today's leaders get displaced by a cheaper or better approach before the spending payback materializes.",
        "risk_level": "higher",
        "source": "filings",
        "keywords": [
            "artificial intelligence", "machine learning", "large language model",
            "generative AI", "AI infrastructure", "GPU",
        ],
        "tickers": [
            "NVDA", "MSFT", "GOOGL", "META", "AMZN", "AMD", "AVGO", "PLTR",
            "SNOW", "CRM", "ORCL", "SMCI", "ANET", "NOW", "TSM", "ARM",
            "MU", "ADBE", "CRWD", "DDOG", "MRVL", "QCOM",
        ],
    },
    {
        "key": "clean-energy-ev",
        "name": "Clean Energy & EVs",
        "description": "Solar, battery, and electric-vehicle makers riding the shift away from fossil fuels.",
        "about": "Clean energy and electric vehicles cover the companies replacing fossil-fuel generation and gasoline engines with solar, wind, batteries, and EVs - from panel and battery manufacturers to the automakers building electric fleets and the utilities integrating renewable power onto the grid.\n\nThe shift toward electrification is a multi-decade trend supported by falling battery costs and growing charging infrastructure, but the industry remains highly sensitive to interest rates (most projects are capital-intensive and debt-funded), government subsidies (which can change with an election), and commodity input costs like lithium. EV adoption in particular has cooled from earlier growth projections, and several companies in this space are still unprofitable, making it one of the more volatile groups in this catalog.",
        "risk_level": "higher",
        "source": "seed",
        "tickers": [
            "TSLA", "ENPH", "FSLR", "SEDG", "RUN", "PLUG", "NEE", "RIVN",
            "LCID", "ALB", "BE", "CHPT", "SHLS", "ARRY", "CSIQ", "AES",
            "BEP", "STEM", "NXT",
        ],
    },
    {
        "key": "cybersecurity",
        "name": "Cybersecurity",
        "description": "Security vendors protecting enterprises and governments from a growing attack surface.",
        "about": "Cybersecurity companies build the software and services that protect networks, devices, and data from unauthorized access - firewalls, endpoint protection, identity management, and the security operations tools that detect and respond to breaches. Demand tends to be resilient because most organizations treat security spending as non-discretionary, even when they cut costs elsewhere.\n\nGrowth is driven by the expanding attack surface created by cloud computing, remote work, and now AI systems that introduce entirely new categories of vulnerability. The flip side is a crowded, fast-consolidating market - a wave of point-solution vendors compete for budget against a handful of large platform players, and being on the losing side of that consolidation (or a single high-profile breach at a portfolio company) can hit a stock hard.",
        "risk_level": "moderate",
        "source": "industry",
        "industry": "Software—Infrastructure",
    },
    {
        "key": "cloud-enterprise-software",
        "name": "Cloud & Enterprise Software",
        "description": "SaaS and cloud-infrastructure platforms that run the back office for other businesses.",
        "about": "Cloud and enterprise software companies sell the subscription-based tools that run a business's back office - CRM, HR, finance, project management, and the cloud infrastructure those applications run on. Recurring subscription revenue makes this group's cash flows more predictable than most.\n\nThe category has matured past its highest-growth years, and much of that growth is now dependent on organizations expanding usage of the tools they already have, not just landing new customers. AI is reshaping the competitive landscape here too - some vendors are the first to bundle AI features profitably, while others risk having their core product commoditized by a cheaper AI-native competitor.",
        "risk_level": "moderate",
        "source": "industry",
        "industry": "Software—Application",
    },
    {
        "key": "healthcare-innovation",
        "name": "Healthcare Innovation",
        "description": "Drugmakers, biotech, and medtech pushing into GLP-1s, gene therapy, and surgical robotics.",
        "about": "Healthcare innovation spans drugmakers, biotech, and medical-device companies pushing into some of the industry's fastest-growing areas - GLP-1 weight-loss and diabetes drugs, gene and cell therapy, and robotic-assisted surgery. Unlike most sectors, demand here is driven less by the economic cycle than by demographics, disease prevalence, and regulatory approval timelines.\n\nThat said, this is a binary-outcome business at the individual-company level: a clinical trial failure or an FDA rejection can erase a large share of a drugmaker's value overnight, and successful drugs eventually face patent expiration and generic competition. Pricing pressure from insurers and government negotiation (particularly in the US) is also a persistent overhang on the group's margins.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "LLY", "NVO", "UNH", "ISRG", "VRTX", "REGN", "DXCM", "ABBV", "MRNA", "PODD",
            "JNJ", "PFE", "TMO", "MDT", "SYK", "BSX", "AMGN", "GILD",
        ],
    },
    {
        "key": "semiconductors",
        "name": "Semiconductors",
        "description": "Chip designers, foundries, and equipment makers behind every AI and consumer device.",
        "about": "Semiconductor companies design and manufacture the chips inside every computer, phone, car, and now AI datacenter - a group that includes chip designers, the foundries that manufacture their designs, and the equipment makers that build the machines foundries use. Nearly every other technology theme in this catalog depends on this one.\n\nThe industry is famously cyclical: demand can swing from shortage to oversupply within a couple of years as customers over-order during booms and work through inventory during slowdowns. It's also geographically concentrated - a large share of the world's advanced chip manufacturing runs through a small number of facilities in Taiwan and South Korea, which is both an efficiency advantage and a geopolitical risk this theme is directly exposed to.",
        "risk_level": "higher",
        "source": "industry",
        "industry": "Semiconductors",
    },
    {
        "key": "fintech-digital-payments",
        "name": "Fintech & Digital Payments",
        "description": "Payment networks and digital-first financial platforms displacing cash and legacy banking.",
        "about": "Fintech and digital payments companies are rebuilding how money moves - card networks, mobile wallets, buy-now-pay-later, and the software platforms banks and merchants use to process transactions online. Growth here tracks the broader shift from cash and checks to digital and card-based payments, a trend that's been running for over a decade and still has room to go in many markets.\n\nBecause this theme sits so close to the financial system, it's exposed to the same forces that hit banks - rising loan losses in a downturn hurt the lenders in this group, and interest-rate swings affect the economics of buy-now-pay-later and consumer credit businesses. Regulatory scrutiny of interchange fees and consumer lending practices is also a recurring risk across the group.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "V", "MA", "PYPL", "XYZ", "COIN", "SOFI", "AXP", "ADYEY", "FISV", "GPN",
            "HOOD", "AFRM", "UPST", "WEX", "FIS", "PAYX",
        ],
    },
    {
        "key": "consumer-ecommerce",
        "name": "Consumer & E-commerce",
        "description": "Online retail, marketplaces, and digital-first consumer brands.",
        "about": "Consumer and e-commerce companies sell directly to shoppers online or through digital-first brands - marketplaces, specialty retailers, and consumer names that built (or are building) a meaningful share of their sales through digital channels. This theme benefits from the long-running shift of retail spending from physical stores to online.\n\nConsumer spending is tightly linked to the economic cycle, so this group tends to underperform when unemployment rises or confidence falls. It's also a low-margin, intensely competitive business where a handful of scaled players can squeeze smaller competitors on price and logistics, and shifting consumer tastes can turn a fast-growing brand into a fading one faster than in most other sectors.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "AMZN", "SHOP", "MELI", "ETSY", "CHWY", "ABNB", "BKNG", "SBUX", "NKE", "CMG",
            "WMT", "TGT", "LULU", "ULTA", "YUM", "TJX",
        ],
    },
    {
        "key": "defense-aerospace",
        "name": "Defense & Aerospace",
        "description": "Defense primes and aerospace suppliers building the hardware behind military and government spending.",
        "about": "Defense and aerospace companies build the aircraft, missiles, satellites, and support services that governments buy for national security, plus the commercial aircraft that airlines fly. Revenue is largely driven by government budgets rather than the economic cycle, which has historically made this group more defensive than the market during downturns.\n\nGovernment contracts come with long lead times and lumpy revenue recognition, so a single program win or cancellation can move a stock meaningfully. Spending levels also depend on the geopolitical environment and the priorities of whichever government is in power - a period of budget tightening or a shift in defense priorities can weigh on the group even if underlying demand for its products hasn't changed.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "LMT", "RTX", "NOC", "GD", "LHX", "HII", "TXT", "AVAV", "KTOS", "BA",
            "LDOS", "SAIC", "HEI", "TDG", "CW", "AXON",
        ],
    },
    {
        "key": "robotics-automation",
        "name": "Robotics & Automation",
        "description": "Industrial robotics, automation, and machine-vision companies reshaping factories and warehouses.",
        "about": "Robotics and automation companies make the machines, sensors, and software that let factories and warehouses run with less manual labor - industrial robots, machine-vision systems, and the control software that ties them together. Rising labor costs and efforts to bring manufacturing closer to home have both pushed companies to invest more in automation.\n\nBecause most of this group's customers are manufacturers, this theme is tied closely to industrial capital spending, which slows sharply when the economy weakens - companies delay automation projects long before they cut other costs. It's also a business where a handful of large industrial conglomerates compete against smaller pure-play automation companies, and the smaller names can be more volatile on both the way up and down.",
        "risk_level": "higher",
        "source": "seed",
        "tickers": [
            "ROK", "FANUY", "TER", "ZBRA", "PATH", "CGNX", "EMR", "HON",
            "ROP", "DOV", "AME", "SYM", "KEYS",
        ],
    },
    {
        "key": "media-entertainment",
        "name": "Media & Entertainment",
        "description": "Streaming platforms, studios, and live-event companies competing for attention and subscriptions.",
        "about": "Media and entertainment companies produce and distribute the shows, movies, music, and live events people pay for or watch ad-supported - streaming platforms, studios, and the companies that own sports and concert rights. The industry has been reshaped over the last decade by the shift from cable and box-office revenue to streaming subscriptions and digital advertising.\n\nStreaming has turned out to be an expensive business to compete in - content costs are high and subscriber growth in mature markets like the US has slowed, pushing several companies toward bundling, ad-supported tiers, and price increases to protect margins. This theme is also sensitive to discretionary consumer spending; entertainment budgets are often among the first things households cut when money is tight.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "NFLX", "DIS", "WBD", "PARA", "SPOT", "ROKU", "LYV", "TTWO", "EA",
            "CMCSA", "FOXA", "WMG", "MTCH", "PINS", "SNAP",
        ],
    },
    {
        "key": "banks-financial-services",
        "name": "Banks & Financial Services",
        "description": "Large money-center and regional banks along with brokerages anchoring the US financial system.",
        "about": "Banks and financial services companies take deposits, make loans, and provide the brokerage and wealth-management services that keep the financial system running. Their profitability is driven largely by the spread between what they pay depositors and what they earn on loans, which moves with the interest-rate cycle.\n\nThis group is directly exposed to credit quality - loan losses rise when unemployment climbs, and a sharp enough downturn can force banks to set aside significant capital for bad loans. Regional and smaller banks in particular can also be more sensitive to deposit outflows during periods of financial stress, as seen in 2023's regional-bank turmoil, even when their underlying loan books are healthy.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "JPM", "BAC", "WFC", "GS", "MS", "SCHW", "C", "USB",
            "PNC", "TFC", "COF", "MTB", "STT", "ALLY",
        ],
    },
    {
        "key": "homebuilders-real-estate",
        "name": "Homebuilders & Real Estate",
        "description": "Homebuilders, developers, and REITs tied to housing supply and commercial property.",
        "about": "Homebuilders and real estate companies build new housing and own the commercial and residential properties leased out through REITs - retail centers, apartments, data centers, and storage facilities. Demand for new housing is driven by population growth, household formation, and how affordable a mortgage is relative to income.\n\nBecause most homebuyers and REITs finance purchases with debt, this theme is one of the most interest-rate-sensitive groups in the catalog - mortgage rates directly affect how much home a buyer can afford, and REITs' borrowing costs affect what they can pay for new properties. A sustained period of high rates can weigh on both new construction and property valuations even if underlying demand for space hasn't changed.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "DHI", "LEN", "NVR", "PHM", "SPG", "O", "AMT", "PLD",
            "PSA", "EQIX", "DLR", "AVB", "EQR",
        ],
    },
    {
        "key": "energy-natural-resources",
        "name": "Energy & Natural Resources",
        "description": "Oil, gas, and pipeline companies producing and moving the fuels that still power the economy.",
        "about": "Energy and natural resources companies find, produce, refine, and transport the oil, natural gas, and fuels that still power most of the global economy - exploration and production companies, refiners, and the pipeline operators that move it all. Profitability here is driven directly by commodity prices, which swing with global supply and demand and geopolitical events.\n\nBecause production decisions made today take years to affect supply, the industry is prone to boom-bust cycles that can be hard to time. It also carries long-term demand risk from the energy transition - even a gradual shift toward renewables and EVs changes the multi-decade demand picture for oil and gas, which shows up in how the market values these companies today.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "WMB", "KMI",
            "PSX", "MPC", "VLO", "APA", "DVN", "FANG",
        ],
    },
    {
        "key": "industrial-infrastructure",
        "name": "Industrial Infrastructure",
        "description": "Heavy-equipment, construction, and infrastructure-spending plays behind roads, grids, and factories.",
        "about": "Industrial infrastructure companies make the heavy equipment and provide the construction and engineering services behind roads, power grids, factories, and data centers - a group that benefits directly from public infrastructure spending and private capital investment in new buildings and facilities. Government infrastructure bills and the AI-driven datacenter buildout have both been tailwinds for this group recently.\n\nOrder books here move with the broader capital-spending cycle - when companies and governments pull back on big projects during a slowdown, this group tends to feel it before consumer-facing sectors do. Many of these businesses also carry significant fixed costs, so their earnings can swing more than revenue does when volumes rise or fall.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "CAT", "DE", "ETN", "PWR", "VMC", "MLM", "URI", "GNRC",
            "ITW", "PH", "JCI", "XYL", "WAB",
        ],
    },
    {
        "key": "travel-leisure",
        "name": "Travel & Leisure",
        "description": "Airlines, hotels, cruise lines, and casinos riding the post-pandemic rebound in travel spending.",
        "about": "Travel and leisure companies - airlines, hotels, cruise lines, and casino operators - sell experiences that depend on people having both the money and the confidence to spend on discretionary trips. The group benefited from a strong rebound in travel demand after the pandemic-era shutdowns.\n\nDiscretionary spending is one of the first things households cut back on when their finances tighten, making this theme highly sensitive to the economic cycle. Airlines and cruise lines also carry heavy fixed costs (planes, ships, fuel) and thin margins even in good years, so a modest drop in demand or a spike in fuel prices can have an outsized effect on profitability.",
        "risk_level": "higher",
        "source": "seed",
        "tickers": [
            "MAR", "RCL", "CCL", "DAL", "LVS", "EXPE", "UAL", "H",
            "WYNN", "MGM", "LUV", "ALK", "TCOM",
        ],
    },
    {
        "key": "space-economy",
        "name": "Space Economy",
        "description": "Launch providers, satellite operators, and space-infrastructure companies commercializing orbit.",
        "about": "The space economy covers the companies launching satellites, operating orbital infrastructure, and building the hardware for a rapidly commercializing space industry - a shift from a business once dominated by government programs to one increasingly funded by private capital and commercial satellite demand (broadband, imaging, communications).\n\nMost companies in this theme are early-stage and not yet consistently profitable, funding ambitious growth plans with capital raised from investors rather than operating cash flow - a riskier setup than the rest of this catalog. Launch failures, program delays, and the sheer capital intensity of building and operating spacecraft are real risks, and the eventual size of the addressable commercial market is still more forecast than proven.",
        "risk_level": "higher",
        "source": "filings",
        "keywords": [
            "satellite", "launch vehicle", "space infrastructure", "orbital", "spacecraft",
        ],
        "tickers": [
            "RKLB", "ASTS", "IRDM", "VSAT", "LMT", "BA", "NOC",
            "TDY", "TRMB", "GSAT", "PL", "RDW",
        ],
    },
    {
        "key": "quantum-computing",
        "name": "Quantum Computing",
        "description": "Early-stage quantum hardware and software companies racing to build practical quantum computers.",
        "about": "Quantum computing uses the principles of quantum mechanics to perform certain calculations far faster than classical computers - potentially transformative for drug discovery, cryptography, and optimization problems, but still an emerging technology with no large-scale commercial application in production today. This theme includes pure-play quantum hardware companies and the larger tech companies running quantum research programs alongside their core businesses.\n\nThis is the most speculative theme in the catalog: most pure-play companies here have little to no revenue and are years away (by most estimates) from quantum computers that reliably outperform classical ones on real-world problems. Stock prices in this group are driven more by sentiment, funding announcements, and headline research milestones than by current earnings, which makes for a lot of volatility in both directions.",
        "risk_level": "higher",
        "source": "filings",
        "keywords": [
            "quantum computing", "qubit", "quantum processor", "quantum algorithm",
        ],
        "tickers": [
            "IONQ", "RGTI", "QBTS", "IBM", "GOOGL", "HON", "ARQQ",
            "MSFT", "AMZN", "NVDA", "INTC",
        ],
    },
    {
        "key": "nuclear-uranium",
        "name": "Nuclear & Uranium",
        "description": "Power utilities, reactor developers, and uranium miners riding AI-datacenter demand for power.",
        "about": "Nuclear and uranium companies operate nuclear power plants, develop next-generation reactor designs, and mine the uranium that fuels them - a segment of the power industry that's seen renewed interest as AI datacenters drive electricity demand higher than grids have seen in decades, and utilities look for reliable, carbon-free power that can run around the clock.\n\nNuclear projects have historically run over budget and behind schedule, and new reactor designs (including the small modular reactors several companies in this theme are developing) are unproven at commercial scale - the technology and cost promises are still largely ahead of actual delivery. Uranium prices are also driven by a relatively thin, concentrated global market, which can make the mining side of this theme more volatile than the utility side.",
        "risk_level": "higher",
        "source": "seed",
        "tickers": [
            "CEG", "VST", "NRG", "CCJ", "SMR", "OKLO", "BWXT", "UEC", "LEU",
            "EXC", "DNN", "UUUU",
        ],
    },
    {
        "key": "data-center-ai-infrastructure",
        "name": "Data Center & AI Infrastructure",
        "description": "The power, cooling, and networking buildout behind AI datacenters, as opposed to the chips and software running inside them.",
        "about": "Data center and AI infrastructure companies build the physical layer behind the AI boom - power distribution, cooling systems, networking equipment, and the data center real estate itself - as distinct from the chips and software running inside those buildings. Surging AI compute demand has driven one of the fastest capital-spending buildouts in recent memory, and this theme sits directly in that path.\n\nMuch of this spending is being funded by a small number of very large technology companies, so this theme's fortunes are tied to their continued willingness to spend at current levels. There's also a real question of whether the industry is building more capacity than will ultimately be needed if AI compute demand growth slows - a risk sometimes described as the space's own version of the early-2000s telecom buildout.",
        "risk_level": "higher",
        "source": "seed",
        "tickers": [
            "VRT", "ETN", "EQIX", "DLR", "MOD", "VST", "PWR", "NVT", "AVAV",
            "AMT", "CCI", "IRM",
        ],
    },
    {
        "key": "consumer-staples-dividends",
        "name": "Consumer Staples & Dividend Aristocrats",
        "description": "Large, cash-generative household-brand companies that keep paying and raising dividends through downturns.",
        "about": "Consumer staples and dividend aristocrats sell the household goods, food, and beverages people buy regardless of the economy - and many have raised their dividends every year for decades, funded by steady, predictable cash flow. That reliability is why this theme is tagged lower risk relative to the rest of the catalog.\n\nThe tradeoff for that stability is limited growth - these are mature, slow-growing businesses, and their stocks tend to lag in a strong bull market even as they hold up better in a downturn. Rising input costs (commodities, packaging, labor) can also squeeze margins if a company can't pass the cost along in price without losing volume, and high dividend payouts leave less room to reinvest in new growth.",
        "risk_level": "lower",
        "source": "seed",
        "tickers": [
            "PG", "KO", "PEP", "CL", "WMT", "COST", "MDLZ", "KMB",
            "MO", "PM", "GIS",
        ],
    },
    {
        "key": "insurance",
        "name": "Insurance",
        "description": "Property, casualty, and life insurers underwriting risk for consumers and businesses.",
        "about": "Insurance companies collect premiums in exchange for taking on financial risk - property and casualty coverage for homes, cars, and businesses, and life and health coverage for individuals. Profitability comes from pricing that risk correctly (underwriting) plus the investment returns earned on the premiums held before claims are paid out.\n\nInsurers are exposed to catastrophe risk - a severe hurricane season or a spike in wildfire losses can produce a very bad year for underwriting results, sometimes forcing large premium increases the following year. Rising interest rates have generally helped insurers' investment income in recent years, but a sharp reversal, or an unexpectedly severe claims environment, can hit the group's earnings quickly.",
        "risk_level": "moderate",
        "source": "seed",
        "tickers": [
            "PGR", "TRV", "ALL", "CB", "MET", "PRU", "AIG",
            "HIG", "AFL", "L",
        ],
    },
    {
        "key": "sports-betting-gaming",
        "name": "Sports Betting & Gaming",
        "description": "Online sportsbooks and casino operators capitalizing on the legalization of sports betting.",
        "about": "Sports betting and gaming companies operate online sportsbooks, casinos, and the gaming equipment behind them - a group that's expanded rapidly as US states have legalized sports betting one by one over the past several years. Growth has been driven almost entirely by that state-by-state legalization wave rather than by the broader economy.\n\nCustomer acquisition in this business has been expensive - operators have spent heavily on promotions and advertising to win market share in new states, which has weighed on profitability even as revenue grew quickly. The group is also exposed to regulatory risk: tax rates on betting revenue and the pace of further state legalization are both decided by state legislatures and can change with little warning.",
        "risk_level": "higher",
        "source": "seed",
        "tickers": [
            "DKNG", "FLUT", "MGM", "CZR", "PENN", "LVS",
            "BYD", "RSI", "CHDN", "WMS",
        ],
    },
    {
        "key": "metals-mining",
        "name": "Metals & Mining",
        "description": "Miners producing the copper, gold, and industrial metals that power construction and electrification.",
        "about": "Metals and mining companies extract the copper, gold, and industrial metals used in construction, electronics, and the broader push toward electrification - copper and other industrial metals in particular are a direct input to the power grid and EV buildout described elsewhere in this catalog. Gold miners behave differently, tending to do best when investors are seeking a safe-haven asset.\n\nMining is a capital-intensive, commodity-price-driven business - a new mine can take a decade and billions of dollars to bring into production, so supply can't respond quickly to a demand spike, and companies can be squeezed hard when metal prices fall below their production costs. Political and permitting risk is also significant, since many of the world's largest ore deposits sit in countries with less predictable regulatory environments than the US.",
        "risk_level": "higher",
        "source": "seed",
        "tickers": [
            "FCX", "NEM", "SCCO", "AA", "CLF",
            "AEM", "GOLD", "MP", "NUE", "STLD",
        ],
    },
]

_THEMES_BY_KEY = {theme["key"]: theme for theme in THEME_CATALOG}

_UNIVERSE_LIMIT = 25
_MIN_MARKET_CAP = 2_000_000_000
_UNIVERSE_CACHE_TTL_SECONDS = 86_400  # a day - industry composition/prices don't shift intraday enough to rescreen every request
_universe_cache: dict[str, tuple[float, list[str]]] = {}


def get_theme(key: str) -> dict:
    """Look up a theme by its key, raising ValueError (not KeyError) for an
    unknown one - same convention as tools.py's get_stock_price/_quote, so
    callers can treat "bad input" uniformly across this codebase."""
    theme = _THEMES_BY_KEY.get(key)
    if theme is None:
        raise ValueError(f"Unknown theme key {key!r}")
    return theme


def _is_valid_ticker(ticker: str) -> bool:
    try:
        get_stock_price(ticker)
        return True
    except ValueError:
        return False


def get_filings_relevance(theme_key: str) -> dict[str, dict]:
    """Ticker -> {relevance_score, rationale} for a theme's most recent
    "kept" filings-scorer picks (see agents/theme_filings_scorer.py) - the
    "why is this ticker in the theme" the API exposes to the Themes tab,
    as opposed to _get_filings_universe's plain ticker list used to build
    the universe itself. Empty for a theme the scorer's never run, or one
    that isn't filings-sourced at all."""
    db = SessionLocal()
    try:
        rows = (
            db.query(ThemeFilingsPick)
            .filter(ThemeFilingsPick.theme_key == theme_key, ThemeFilingsPick.status == "kept")
            .all()
        )
        return {row.ticker: {"relevance_score": row.relevance_score, "rationale": row.rationale} for row in rows}
    finally:
        db.close()


def _get_filings_universe(theme_key: str) -> list[str]:
    """Tickers from the most recent agents/theme_filings_scorer.py run for
    this theme, ranked by relevance_score - empty if the scorer's never
    been run for it, so the caller falls back to the theme's seed list."""
    db = SessionLocal()
    try:
        rows = (
            db.query(ThemeFilingsPick)
            .filter(ThemeFilingsPick.theme_key == theme_key, ThemeFilingsPick.status == "kept")
            .order_by(ThemeFilingsPick.relevance_score.desc())
            .all()
        )
        return [row.ticker for row in rows]
    finally:
        db.close()


def get_theme_universe(theme_key: str) -> list[str]:
    """This theme's actual ticker universe: a live industry screen or the
    static seed list (per theme["source"]), filtered to tickers with a
    fetchable live price - the general fix for the CYBR problem, applied
    to every theme regardless of how its candidates were sourced. Cached
    per theme for _UNIVERSE_CACHE_TTL_SECONDS so repeat page loads don't
    re-run the screen/validity checks every time (same hand-rolled TTL
    pattern as tools.py's _info_cache)."""
    cached = _universe_cache.get(theme_key)
    if cached is not None and monotonic() - cached[0] < _UNIVERSE_CACHE_TTL_SECONDS:
        return cached[1]

    theme = get_theme(theme_key)
    if theme["source"] == "industry":
        candidates = screen_by_industry(theme["industry"], min_market_cap=_MIN_MARKET_CAP, limit=_UNIVERSE_LIMIT)
    elif theme["source"] == "filings":
        candidates = _get_filings_universe(theme_key) or theme["tickers"]
    else:
        candidates = theme["tickers"]

    valid = [ticker for ticker, ok in zip(candidates, parallel_map(_is_valid_ticker, candidates)) if ok]
    _universe_cache[theme_key] = (monotonic(), valid)
    return valid
