from flask import Flask, request, render_template_string
import yfinance as yf
import pandas as pd
import threading
import queue

# --- CONFIGURATION ---
HIGHER_IS_BETTER = {
    'current_ratio': True, 'quick_ratio': True, 'debt_to_equity': False,
    'debt_to_assets': False, 'interest_coverage': True, 'gross_profit_margin': True,
    'net_profit_margin': True, 'roe': True, 'roa': True, 'asset_turnover': True,
    'pe_ratio': None, 'ev_to_ebitda': None, 'price_to_book': None,
}

# A list of prominent NSE companies for the dropdowns
# Format: ('TICKER.NS', 'Company Name')
NSE_COMPANIES = sorted([
    ('RELIANCE.NS', 'Reliance Industries Ltd'),
    ('TCS.NS', 'Tata Consultancy Services Ltd'),
    ('HDFCBANK.NS', 'HDFC Bank Ltd'),
    ('INFY.NS', 'Infosys Ltd'),
    ('ICICIBANK.NS', 'ICICI Bank Ltd'),
    ('HINDUNILVR.NS', 'Hindustan Unilever Ltd'),
    ('SBIN.NS', 'State Bank of India'),
    ('BHARTIARTL.NS', 'Bharti Airtel Ltd'),
    ('BAJFINANCE.NS', 'Bajaj Finance Ltd'),
    ('KOTAKBANK.NS', 'Kotak Mahindra Bank Ltd'),
    ('LT.NS', 'Larsen & Toubro Ltd'),
    ('HCLTECH.NS', 'HCL Technologies Ltd'),
    ('AXISBANK.NS', 'Axis Bank Ltd'),
    ('MARUTI.NS', 'Maruti Suzuki India Ltd'),
    ('ITC.NS', 'ITC Ltd'),
    ('ASIANPAINT.NS', 'Asian Paints Ltd'),
    ('WIPRO.NS', 'Wipro Ltd'),
    ('DMART.NS', 'Avenue Supermarts Ltd'),
    ('ULTRACEMCO.NS', 'UltraTech Cement Ltd'),
    ('NESTLEIND.NS', 'Nestle India Ltd'),
    ('BAJAJFINSV.NS', 'Bajaj Finserv Ltd'),
    ('M&M.NS', 'Mahindra & Mahindra Ltd'),
    ('POWERGRID.NS', 'Power Grid Corporation of India Ltd'),
    ('TITAN.NS', 'Titan Company Ltd'),
    ('SUNPHARMA.NS', 'Sun Pharmaceutical Industries Ltd'),
    ('NTPC.NS', 'NTPC Ltd'),
    ('TATAMOTORS.NS', 'Tata Motors Ltd'),
    ('ONGC.NS', 'Oil & Natural Gas Corporation Ltd'),
    ('ADANIENT.NS', 'Adani Enterprises Ltd'),
    ('JSWSTEEL.NS', 'JSW Steel Ltd'),
    ('TATASTEEL.NS', 'Tata Steel Ltd'),
    ('COALINDIA.NS', 'Coal India Ltd'),
    ('INDUSINDBK.NS', 'IndusInd Bank Ltd'),
    ('HINDALCO.NS', 'Hindalco Industries Ltd'),
    ('GRASIM.NS', 'Grasim Industries Ltd'),
    ('ADANIPORTS.NS', 'Adani Ports and Special Economic Zone Ltd'),
    ('CIPLA.NS', 'Cipla Ltd'),
    ('EICHERMOT.NS', 'Eicher Motors Ltd'),
    ('TECHM.NS', 'Tech Mahindra Ltd'),
    ('BPCL.NS', 'Bharat Petroleum Corporation Ltd'),
    ('BRITANNIA.NS', 'Britannia Industries Ltd'),
    ('DIVISLAB.NS', 'Divi\'s Laboratories Ltd'),
    ('HEROMOTOCO.NS', 'Hero MotoCorp Ltd'),
    ('DRREDDY.NS', 'Dr. Reddy\'s Laboratories Ltd'),
    ('APOLLOHOSP.NS', 'Apollo Hospitals Enterprise Ltd'),
    ('UPL.NS', 'UPL Ltd'),
    ('BAJAJ-AUTO.NS', 'Bajaj Auto Ltd'),
    ('SHREECEM.NS', 'Shree Cement Ltd'),
    ('INDIGO.NS', 'InterGlobe Aviation Ltd'),
    ('TATACONSUM.NS', 'Tata Consumer Products Ltd')
], key=lambda x: x[1]) # Sort by company name

# --- 1. DATA FETCHING & PROCESSING (Works for any market) ---

def get_financial_data(ticker_symbol, data_queue):
    """
    Fetches financial data for a ticker and puts the result into a thread-safe queue.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        
        if not info or info.get('trailingEps') is None:
            data_queue.put({ticker_symbol: None, 'error': f"Invalid or delisted ticker: {ticker_symbol}. Could not fetch data."})
            return
            
        balance_sheet = ticker.balance_sheet
        income_stmt = ticker.income_stmt
        
        if balance_sheet.empty or income_stmt.empty or 'Stockholders Equity' not in balance_sheet.index:
            data_queue.put({ticker_symbol: None, 'error': f"Could not fetch complete financial statements for {ticker_symbol}."})
            return

        if len(balance_sheet.columns) < 2:
            data_queue.put({ticker_symbol: None, 'error': f"Not enough historical data for {ticker_symbol} to calculate averages."})
            return

        bs_curr = balance_sheet.iloc[:, 0]
        bs_prev = balance_sheet.iloc[:, 1]
        is_curr = income_stmt.iloc[:, 0]
        
        data = {
            "current_assets": bs_curr.get('Current Assets'), "current_liabilities": bs_curr.get('Current Liabilities'),
            "inventory": bs_curr.get('Inventory'), "total_debt": bs_curr.get('Total Debt'),
            "total_equity": bs_curr.get('Stockholders Equity'), "cash": bs_curr.get('Cash And Cash Equivalents'),
            "total_assets": bs_curr.get('Total Assets'), "total_revenue": is_curr.get('Total Revenue'),
            "gross_profit": is_curr.get('Gross Profit'), "ebit": is_curr.get('EBIT'), "ebitda": info.get('ebitda'),
            "interest_expense": is_curr.get('Interest Expense'), "net_income": is_curr.get('Net Income'),
            "avg_total_assets": (bs_curr.get('Total Assets', 0) + bs_prev.get('Total Assets', 0)) / 2,
            "avg_total_equity": (bs_curr.get('Stockholders Equity', 0) + bs_prev.get('Stockholders Equity', 0)) / 2,
            "current_share_price": info.get('currentPrice') or info.get('previousClose'), "eps": info.get('trailingEps'),
            "market_cap": info.get('marketCap'), "book_value_per_share": info.get('bookValue'),
        }
        data_queue.put({ticker_symbol: data})
        
    except Exception:
        data_queue.put({ticker_symbol: None, 'error': f"An error occurred fetching data for {ticker_symbol}. It may be an invalid ticker."})

def calculate_ratios(data):
    """Calculates all ratios from the input data dict."""
    if not data: return {}
    ratios = {}
    def safe_divide(num, den): return None if den is None or den == 0 or num is None else num / den

    ratios['current_ratio'] = safe_divide(data.get('current_assets'), data.get('current_liabilities'))
    quick_assets = (data.get('current_assets') or 0) - (data.get('inventory') or 0)
    ratios['quick_ratio'] = safe_divide(quick_assets, data.get('current_liabilities'))
    ratios['debt_to_equity'] = safe_divide(data.get('total_debt'), data.get('total_equity'))
    ratios['debt_to_assets'] = safe_divide(data.get('total_debt'), data.get('total_assets'))
    ratios['interest_coverage'] = safe_divide(data.get('ebit'), data.get('interest_expense'))
    ratios['gross_profit_margin'] = safe_divide(data.get('gross_profit'), data.get('total_revenue'))
    ratios['net_profit_margin'] = safe_divide(data.get('net_income'), data.get('total_revenue'))
    ratios['roe'] = safe_divide(data.get('net_income'), data.get('avg_total_equity'))
    ratios['roa'] = safe_divide(data.get('net_income'), data.get('avg_total_assets'))
    ratios['asset_turnover'] = safe_divide(data.get('total_revenue'), data.get('avg_total_assets'))
    ratios['pe_ratio'] = safe_divide(data.get('current_share_price'), data.get('eps'))
    enterprise_value = (data.get('market_cap') or 0) + (data.get('total_debt') or 0) - (data.get('cash') or 0)
    ratios['ev_to_ebitda'] = safe_divide(enterprise_value, data.get('ebitda'))
    ratios['price_to_book'] = safe_divide(data.get('current_share_price'), data.get('book_value_per_share'))
    return ratios

def calculate_benchmark_averages(competitor_ratios_list):
    """Calculates the average for each ratio from a list of competitor ratio dicts."""
    if not competitor_ratios_list: return {}
    all_ratio_names = competitor_ratios_list[0].keys()
    benchmark_ratios = {}
    for name in all_ratio_names:
        valid_values = [ratios[name] for ratios in competitor_ratios_list if ratios.get(name) is not None]
        benchmark_ratios[name] = sum(valid_values) / len(valid_values) if valid_values else None
    return benchmark_ratios

# --- 2. FLASK APPLICATION & ROUTING ---

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Financial Ratio Analysis by Rakesh KS (Indian Market)</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <!-- Select2 CSS -->
    <link href="https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/css/select2.min.css" rel="stylesheet" />
    <style>
        body { font-family: 'Inter', sans-serif; background-color: #f3f4f6; }
        .spinner { border-top-color: #3498db; animation: spin 1s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        /* Style Select2 to match Tailwind form elements */
        .select2-container .select2-selection--single { height: 2.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem; }
        .select2-container--default .select2-selection--single .select2-selection__rendered { line-height: 2.5rem; padding-left: 0.75rem; }
        .select2-container--default .select2-selection--single .select2-selection__arrow { height: 2.5rem; }
        .select2-container .select2-selection--multiple { min-height: 2.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem; }
        .select2-dropdown { border: 1px solid #d1d5db; border-radius: 0.375rem; }
    </style>
</head>
<body class="p-4 md:p-8">
    <div class="max-w-4xl mx-auto bg-white rounded-xl shadow-lg p-6 md:p-8">
        <div class="text-center mb-8">
            <h1 class="text-3xl md:text-4xl font-bold text-gray-800">Indian Market Financial Analysis by Rakesh KS</h1>
            <p class="text-gray-500 mt-2">Select a company and its competitors to generate a comparative analysis.</p>
        </div>

        <!-- Input Form -->
        <form method="POST" id="analysis-form" class="space-y-4">
            <div>
                <label for="ticker" class="block text-sm font-medium text-gray-700">Company Ticker</label>
                <select name="ticker" id="ticker"
                       class="mt-1 block w-full">
                    {% for symbol, name in company_list %}
                        <option value="{{ symbol }}" {% if symbol == selected_ticker %}selected{% endif %}>{{ name }} ({{ symbol }})</option>
                    {% endfor %}
                </select>
            </div>
            <div>
                <label for="competitors" class="block text-sm font-medium text-gray-700">Competitor Tickers</label>
                <select name="competitors" id="competitors" multiple
                       class="mt-1 block w-full">
                    {% for symbol, name in company_list %}
                        <option value="{{ symbol }}" {% if symbol in selected_competitors %}selected{% endif %}>{{ name }} ({{ symbol }})</option>
                    {% endfor %}
                </select>
            </div>
            <div class="text-center">
                <button type="submit" id="submit-button"
                        class="inline-flex items-center justify-center w-full md:w-auto px-6 py-3 border border-transparent text-base font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition-colors">
                    <span id="button-text">Analyze</span>
                    <div id="button-spinner" class="spinner w-5 h-5 rounded-full border-2 border-t-2 border-white ml-3 hidden"></div>
                </button>
            </div>
        </form>

        <!-- Results Section -->
        {% if results %}
        <div class="mt-10">
            {% if results.error %}
            <div class="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 rounded-md" role="alert">
                <p class="font-bold">Error</p>
                <p>{{ results.error }}</p>
            </div>
            {% else %}
            <h2 class="text-2xl font-bold text-gray-800 text-center">Analysis for: {{ results.ticker.upper() }}</h2>
            <p class="text-center text-gray-500 mb-6">Compared against the average of: {{ results.competitors|join(', ') }}</p>
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Ratio</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Company Value</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Benchmark Avg</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Analysis</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {% for row in results.analysis %}
                        <tr>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{{ row.ratio_name }}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{{ row.company_value }}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{{ row.benchmark_value }}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-semibold {{ row.color_class }}">{{ row.analysis }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% endif %}
        </div>
        {% endif %}
    </div>

    <!-- JQuery and Select2 JS -->
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/js/select2.min.js"></script>
    <script>
        $(document).ready(function() {
            // Initialize Select2
            $('#ticker').select2();
            $('#competitors').select2();
        });

        document.getElementById('analysis-form').addEventListener('submit', function() {
            document.getElementById('button-text').classList.add('hidden');
            document.getElementById('button-spinner').classList.remove('hidden');
            document.getElementById('submit-button').disabled = true;
        });
    </script>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    selected_ticker = 'RELIANCE.NS'
    selected_competitors = ['TCS.NS', 'INFY.NS', 'HDFCBANK.NS']
    
    if request.method == 'POST':
        ticker = request.form.get('ticker')
        competitor_tickers = request.form.getlist('competitors')
        
        selected_ticker = ticker
        selected_competitors = competitor_tickers

        if not ticker or not competitor_tickers:
            return render_template_string(HTML_TEMPLATE, 
                                          results={'error': 'Please select a company and at least one competitor.'},
                                          company_list=NSE_COMPANIES,
                                          selected_ticker=selected_ticker,
                                          selected_competitors=selected_competitors)

        all_tickers = [ticker] + competitor_tickers

        data_queue = queue.Queue()
        threads = []
        for t in all_tickers:
            thread = threading.Thread(target=get_financial_data, args=(t, data_queue))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()

        all_data = {}
        errors = []
        while not data_queue.empty():
            item = data_queue.get()
            if item.get('error'): errors.append(item['error'])
            all_data.update(item)
        
        if ticker not in all_data or all_data[ticker] is None:
             return render_template_string(HTML_TEMPLATE, 
                                           results={'error': f"Failed to fetch data for main ticker {ticker}. Please check the ticker symbol. Details: {errors}"},
                                           company_list=NSE_COMPANIES,
                                           selected_ticker=selected_ticker,
                                           selected_competitors=selected_competitors)

        company_data = all_data[ticker]
        company_ratios = calculate_ratios(company_data)

        competitor_ratios_list = [calculate_ratios(all_data[comp]) for comp in competitor_tickers if all_data.get(comp)]
        
        if not competitor_ratios_list:
             return render_template_string(HTML_TEMPLATE, 
                                           results={'error': f"Could not fetch valid data for any of the competitors. Cannot create a benchmark. Details: {errors}"},
                                           company_list=NSE_COMPANIES,
                                           selected_ticker=selected_ticker,
                                           selected_competitors=selected_competitors)

        benchmarks = calculate_benchmark_averages(competitor_ratios_list)
        
        analysis_list = []
        for ratio_name, company_value in company_ratios.items():
            row = {'ratio_name': ratio_name.replace('_', ' ').title()}
            if company_value is None:
                row.update({'company_value': 'N/A', 'benchmark_value': '-', 'analysis': 'Data missing', 'color_class': 'text-gray-500'})
                analysis_list.append(row)
                continue

            benchmark_value = benchmarks.get(ratio_name)
            row['company_value'] = f"{company_value:.2f}"
            
            if benchmark_value is None:
                row.update({'benchmark_value': 'N/A', 'analysis': 'No benchmark data', 'color_class': 'text-gray-500'})
                analysis_list.append(row)
                continue
            
            row['benchmark_value'] = f"{benchmark_value:.2f}"
            
            direction = HIGHER_IS_BETTER.get(ratio_name)
            diff = ((company_value - benchmark_value) / abs(benchmark_value)) * 100 if benchmark_value != 0 else 0

            if direction is None:
                row['analysis'] = f"Peers ({diff:+.1f}%)"
                row['color_class'] = 'text-blue-600'
            elif (company_value > benchmark_value and direction) or (company_value < benchmark_value and not direction):
                row['analysis'] = f"GOOD ({diff:+.1f}%)"
                row['color_class'] = 'text-green-600'
            else:
                row['analysis'] = f"POOR ({diff:+.1f}%)"
                row['color_class'] = 'text-red-600'
            
            analysis_list.append(row)

        return render_template_string(HTML_TEMPLATE, 
                                      results={'ticker': ticker, 'competitors': competitor_tickers, 'analysis': analysis_list},
                                      company_list=NSE_COMPANIES,
                                      selected_ticker=selected_ticker,
                                      selected_competitors=selected_competitors)

    return render_template_string(HTML_TEMPLATE, 
                                  company_list=NSE_COMPANIES,
                                  selected_ticker=selected_ticker,
                                  selected_competitors=selected_competitors)

if __name__ == '__main__':
    app.run(debug=True)


