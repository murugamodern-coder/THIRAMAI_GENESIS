"""
Curated NSE-oriented names for fuzzy resolution (Yahoo Finance suffix .NS).

Expand over time; used only for matching user-typed company names to tickers.
"""

from __future__ import annotations

from typing import Final

# yahoo: primary Yahoo symbol; base: NSE trading symbol (approx); name: issuer name for fuzzy text
INDIAN_EQUITIES: Final[list[dict[str, str]]] = [
    {"yahoo": "SUZLON.NS", "base": "SUZLON", "name": "Suzlon Energy Limited"},
    {"yahoo": "IDEA.NS", "base": "IDEA", "name": "Vodafone Idea Limited"},
    {"yahoo": "RELIANCE.NS", "base": "RELIANCE", "name": "Reliance Industries Limited"},
    {"yahoo": "TCS.NS", "base": "TCS", "name": "Tata Consultancy Services Limited"},
    {"yahoo": "INFY.NS", "base": "INFY", "name": "Infosys Limited"},
    {"yahoo": "HDFCBANK.NS", "base": "HDFCBANK", "name": "HDFC Bank Limited"},
    {"yahoo": "ICICIBANK.NS", "base": "ICICIBANK", "name": "ICICI Bank Limited"},
    {"yahoo": "SBIN.NS", "base": "SBIN", "name": "State Bank of India"},
    {"yahoo": "BHARTIARTL.NS", "base": "BHARTIARTL", "name": "Bharti Airtel Limited"},
    {"yahoo": "ITC.NS", "base": "ITC", "name": "ITC Limited"},
    {"yahoo": "KOTAKBANK.NS", "base": "KOTAKBANK", "name": "Kotak Mahindra Bank Limited"},
    {"yahoo": "LT.NS", "base": "LT", "name": "Larsen & Toubro Limited"},
    {"yahoo": "HINDUNILVR.NS", "base": "HINDUNILVR", "name": "Hindustan Unilever Limited"},
    {"yahoo": "AXISBANK.NS", "base": "AXISBANK", "name": "Axis Bank Limited"},
    {"yahoo": "ASIANPAINT.NS", "base": "ASIANPAINT", "name": "Asian Paints Limited"},
    {"yahoo": "MARUTI.NS", "base": "MARUTI", "name": "Maruti Suzuki India Limited"},
    {"yahoo": "TITAN.NS", "base": "TITAN", "name": "Titan Company Limited"},
    {"yahoo": "SUNPHARMA.NS", "base": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Limited"},
    {"yahoo": "TATAMOTORS.NS", "base": "TATAMOTORS", "name": "Tata Motors Limited"},
    {"yahoo": "WIPRO.NS", "base": "WIPRO", "name": "Wipro Limited"},
    {"yahoo": "ULTRACEMCO.NS", "base": "ULTRACEMCO", "name": "UltraTech Cement Limited"},
    {"yahoo": "NESTLEIND.NS", "base": "NESTLEIND", "name": "Nestle India Limited"},
    {"yahoo": "POWERGRID.NS", "base": "POWERGRID", "name": "Power Grid Corporation of India Limited"},
    {"yahoo": "NTPC.NS", "base": "NTPC", "name": "NTPC Limited"},
    {"yahoo": "ONGC.NS", "base": "ONGC", "name": "Oil and Natural Gas Corporation Limited"},
    {"yahoo": "ADANIENT.NS", "base": "ADANIENT", "name": "Adani Enterprises Limited"},
    {"yahoo": "ADANIGREEN.NS", "base": "ADANIGREEN", "name": "Adani Green Energy Limited"},
    {"yahoo": "ADANIPORTS.NS", "base": "ADANIPORTS", "name": "Adani Ports and Special Economic Zone Limited"},
    {"yahoo": "JSWSTEEL.NS", "base": "JSWSTEEL", "name": "JSW Steel Limited"},
    {"yahoo": "HCLTECH.NS", "base": "HCLTECH", "name": "HCL Technologies Limited"},
    {"yahoo": "TECHM.NS", "base": "TECHM", "name": "Tech Mahindra Limited"},
    {"yahoo": "BAJFINANCE.NS", "base": "BAJFINANCE", "name": "Bajaj Finance Limited"},
    {"yahoo": "BAJAJFINSV.NS", "base": "BAJAJFINSV", "name": "Bajaj Finserv Limited"},
    {"yahoo": "TATASTEEL.NS", "base": "TATASTEEL", "name": "Tata Steel Limited"},
    {"yahoo": "INDIGO.NS", "base": "INDIGO", "name": "InterGlobe Aviation Limited"},
    {"yahoo": "DIVISLAB.NS", "base": "DIVISLAB", "name": "Divi's Laboratories Limited"},
    {"yahoo": "EICHERMOT.NS", "base": "EICHERMOT", "name": "Eicher Motors Limited"},
    {"yahoo": "DRREDDY.NS", "base": "DRREDDY", "name": "Dr. Reddy's Laboratories Limited"},
    {"yahoo": "CIPLA.NS", "base": "CIPLA", "name": "Cipla Limited"},
    {"yahoo": "HEROMOTOCO.NS", "base": "HEROMOTOCO", "name": "Hero MotoCorp Limited"},
    {"yahoo": "APOLLOHOSP.NS", "base": "APOLLOHOSP", "name": "Apollo Hospitals Enterprise Limited"},
    {"yahoo": "BPCL.NS", "base": "BPCL", "name": "Bharat Petroleum Corporation Limited"},
    {"yahoo": "COALINDIA.NS", "base": "COALINDIA", "name": "Coal India Limited"},
    {"yahoo": "GRASIM.NS", "base": "GRASIM", "name": "Grasim Industries Limited"},
    {"yahoo": "HINDALCO.NS", "base": "HINDALCO", "name": "Hindalco Industries Limited"},
    {"yahoo": "INDUSINDBK.NS", "base": "INDUSINDBK", "name": "IndusInd Bank Limited"},
    {"yahoo": "M&M.NS", "base": "M&M", "name": "Mahindra & Mahindra Limited"},
    {"yahoo": "SBILIFE.NS", "base": "SBILIFE", "name": "SBI Life Insurance Company Limited"},
    {"yahoo": "TATACONSUM.NS", "base": "TATACONSUM", "name": "Tata Consumer Products Limited"},
    {"yahoo": "UPL.NS", "base": "UPL", "name": "UPL Limited"},
    {"yahoo": "VEDL.NS", "base": "VEDL", "name": "Vedanta Limited"},
    {"yahoo": "ZOMATO.NS", "base": "ZOMATO", "name": "Zomato Limited"},
    {"yahoo": "PAYTM.NS", "base": "PAYTM", "name": "One 97 Communications Limited"},
    {"yahoo": "IRCTC.NS", "base": "IRCTC", "name": "Indian Railway Catering and Tourism Corporation Limited"},
    {"yahoo": "LICI.NS", "base": "LICI", "name": "Life Insurance Corporation of India"},
    {"yahoo": "DMART.NS", "base": "DMART", "name": "Avenue Supermarts Limited"},
    {"yahoo": "PIDILITIND.NS", "base": "PIDILITIND", "name": "Pidilite Industries Limited"},
    {"yahoo": "SIEMENS.NS", "base": "SIEMENS", "name": "Siemens Limited"},
    {"yahoo": "HAL.NS", "base": "HAL", "name": "Hindustan Aeronautics Limited"},
    {"yahoo": "BEL.NS", "base": "BEL", "name": "Bharat Electronics Limited"},
    {"yahoo": "COCHINSHIP.NS", "base": "COCHINSHIP", "name": "Cochin Shipyard Limited"},
    {"yahoo": "GAIL.NS", "base": "GAIL", "name": "GAIL (India) Limited"},
    {"yahoo": "IOC.NS", "base": "IOC", "name": "Indian Oil Corporation Limited"},
    {"yahoo": "MOTHERSON.NS", "base": "MOTHERSON", "name": "Samvardhana Motherson International Limited"},
    {"yahoo": "PIIND.NS", "base": "PIIND", "name": "PI Industries Limited"},
    {"yahoo": "POLYCAB.NS", "base": "POLYCAB", "name": "Polycab India Limited"},
    {"yahoo": "SHREECEM.NS", "base": "SHREECEM", "name": "Shree Cement Limited"},
    {"yahoo": "TVSMOTOR.NS", "base": "TVSMOTOR", "name": "TVS Motor Company Limited"},
    {"yahoo": "DABUR.NS", "base": "DABUR", "name": "Dabur India Limited"},
    {"yahoo": "GODREJCP.NS", "base": "GODREJCP", "name": "Godrej Consumer Products Limited"},
    {"yahoo": "MARICO.NS", "base": "MARICO", "name": "Marico Limited"},
    {"yahoo": "BERGEPAINT.NS", "base": "BERGEPAINT", "name": "Berger Paints India Limited"},
    {"yahoo": "PAGEIND.NS", "base": "PAGEIND", "name": "Page Industries Limited"},
    {"yahoo": "HAVELLS.NS", "base": "HAVELLS", "name": "Havells India Limited"},
    {"yahoo": "AMBUJACEM.NS", "base": "AMBUJACEM", "name": "Ambuja Cements Limited"},
    {"yahoo": "ACC.NS", "base": "ACC", "name": "ACC Limited"},
    {"yahoo": "BANKBARODA.NS", "base": "BANKBARODA", "name": "Bank of Baroda"},
    {"yahoo": "CANBK.NS", "base": "CANBK", "name": "Canara Bank"},
    {"yahoo": "PNB.NS", "base": "PNB", "name": "Punjab National Bank"},
    {"yahoo": "UNIONBANK.NS", "base": "UNIONBANK", "name": "Union Bank of India"},
    {"yahoo": "FEDERALBNK.NS", "base": "FEDERALBNK", "name": "The Federal Bank Limited"},
    {"yahoo": "IDFCFIRSTB.NS", "base": "IDFCFIRSTB", "name": "IDFC First Bank Limited"},
    {"yahoo": "YESBANK.NS", "base": "YESBANK", "name": "Yes Bank Limited"},
    {"yahoo": "JINDALSTEL.NS", "base": "JINDALSTEL", "name": "Jindal Steel & Power Limited"},
    {"yahoo": "NMDC.NS", "base": "NMDC", "name": "NMDC Limited"},
    {"yahoo": "SAIL.NS", "base": "SAIL", "name": "Steel Authority of India Limited"},
    {"yahoo": "RECLTD.NS", "base": "RECLTD", "name": "REC Limited"},
    {"yahoo": "PFC.NS", "base": "PFC", "name": "Power Finance Corporation Limited"},
    {"yahoo": "IRFC.NS", "base": "IRFC", "name": "Indian Railway Finance Corporation Limited"},
    {"yahoo": "RVNL.NS", "base": "RVNL", "name": "Rail Vikas Nigam Limited"},
    {"yahoo": "NBCC.NS", "base": "NBCC", "name": "NBCC (India) Limited"},
    {"yahoo": "NCC.NS", "base": "NCC", "name": "NCC Limited"},
    {"yahoo": "LUPIN.NS", "base": "LUPIN", "name": "Lupin Limited"},
    {"yahoo": "BIOCON.NS", "base": "BIOCON", "name": "Biocon Limited"},
    {"yahoo": "AUROPHARMA.NS", "base": "AUROPHARMA", "name": "Aurobindo Pharma Limited"},
    {"yahoo": "TORNTPHARM.NS", "base": "TORNTPHARM", "name": "Torrent Pharmaceuticals Limited"},
    {"yahoo": "MANKIND.NS", "base": "MANKIND", "name": "Mankind Pharma Limited"},
    {"yahoo": "MAXHEALTH.NS", "base": "MAXHEALTH", "name": "Max Healthcare Institute Limited"},
    {"yahoo": "FORTIS.NS", "base": "FORTIS", "name": "Fortis Healthcare Limited"},
    {"yahoo": "COLPAL.NS", "base": "COLPAL", "name": "Colgate Palmolive (India) Limited"},
    {"yahoo": "BRITANNIA.NS", "base": "BRITANNIA", "name": "Britannia Industries Limited"},
    {"yahoo": "VBL.NS", "base": "VBL", "name": "Varun Beverages Limited"},
    {"yahoo": "TRENT.NS", "base": "TRENT", "name": "Trent Limited"},
    {"yahoo": "VOLTAS.NS", "base": "VOLTAS", "name": "Voltas Limited"},
    {"yahoo": "CUMMINSIND.NS", "base": "CUMMINSIND", "name": "Cummins India Limited"},
    {"yahoo": "BOSCHLTD.NS", "base": "BOSCHLTD", "name": "Bosch Limited"},
    {"yahoo": "SCHAEFFLER.NS", "base": "SCHAEFFLER", "name": "Schaeffler India Limited"},
    {"yahoo": "OFSS.NS", "base": "OFSS", "name": "Oracle Financial Services Software Limited"},
    {"yahoo": "PERSISTENT.NS", "base": "PERSISTENT", "name": "Persistent Systems Limited"},
    {"yahoo": "MPHASIS.NS", "base": "MPHASIS", "name": "Mphasis Limited"},
    {"yahoo": "LTIM.NS", "base": "LTIM", "name": "LTIMindtree Limited"},
    {"yahoo": "COFORGE.NS", "base": "COFORGE", "name": "Coforge Limited"},
]


def row_by_yahoo(yahoo: str) -> dict[str, str] | None:
    y = (yahoo or "").strip().upper()
    for row in INDIAN_EQUITIES:
        if row["yahoo"].upper() == y:
            return row
    return None


def row_by_base(base: str) -> dict[str, str] | None:
    b = (base or "").strip().upper().replace(".NS", "").replace(".BO", "")
    for row in INDIAN_EQUITIES:
        if row["base"].upper() == b:
            return row
    return None
