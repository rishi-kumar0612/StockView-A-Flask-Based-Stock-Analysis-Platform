import webbrowser
from threading import Timer
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import sqlite3
import plotly
import plotly.graph_objs as go
import json
import bcrypt
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'

def connect_db():
    return sqlite3.connect('portfolio.db')

app.config['ENV'] = 'development'
app.config['DEBUG'] = True

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'user_id' not in session:
        flash("You need to login first")
        return redirect(url_for('login'))
    
    if request.method == 'GET':
        return render_template('index.html')

    ticker = request.form.get('ticker')
    start = request.form.get('start')
    end = request.form.get('end')
    data, user_ticker_company_name = get_info(ticker, start, end)

    if data.empty:
        flash("No data found for ticker.")
        return render_template('index.html', user_ticker_company_name="No data")

    write_to_db(data, session['user_id'])
    user_ticker = read_from_db(session['user_id'])

    if user_ticker.empty:
        flash("No data available for this ticker.")
        return render_template('index.html', user_ticker_company_name=user_ticker_company_name)

    start, end = read_dates_from_db(session['user_id'])
    end = increase_date_by_1(end)
    spy_ticker, spy_ticker_company_name = get_info('SPY', start, end)

    plot1 = create_line_plot(user_ticker, user_ticker_company_name)
    plot2 = create_candlestick_plot(user_ticker, user_ticker_company_name)
    plot3 = create_macd_plot(user_ticker, user_ticker_company_name)
    average, plot4 = create_moving_average_plot(user_ticker, user_ticker_company_name)
    rsi, plot5 = create_rsi_plot(user_ticker, user_ticker_company_name)
    plot6 = create_comparison_plot(user_ticker, spy_ticker, user_ticker_company_name, spy_ticker_company_name)
    volume = round(user_ticker['Volume'].iloc[-1], 2) if not user_ticker.empty else None
    price = round(user_ticker['Close'].iloc[-1], 2) if not user_ticker.empty else None
    buy_sell = buy_or_sell(rsi)

    return render_template('index.html', plot1=plot1, plot2=plot2, plot3=plot3, plot4=plot4, plot5=plot5,
                           plot6=plot6, user_ticker_company_name=user_ticker_company_name, price=price,
                           volume=volume, rsi=rsi, average=average, buy_sell=buy_sell, ticker=ticker, start=start, end=end)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')

        conn = sqlite3.connect('portfolio.db')
        c = conn.cursor()
        c.execute('SELECT id, password FROM users WHERE username=?', (username,))
        user = c.fetchone()
        conn.close()

        if user and bcrypt.checkpw(password, user[1]):
            session['username'] = username
            session['user_id'] = user[0]
            return redirect(url_for('index'))
        else:
            flash('Login Failed. Please try again.')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('user_id', None)
    return redirect(url_for('login'))


from datetime import datetime

def display_portfolio():
    if 'user_id' not in session:
        flash("You need to login first")
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = connect_db()
    c = conn.cursor()
    portfolios = c.execute('SELECT * FROM Portfolio WHERE user_id = ?', (user_id,)).fetchall()
    conn.close()

    # Convert the portfolios data into a list of dictionaries for easier manipulation
    portfolio_data = {}
    for portfolio in portfolios:
        ticker = portfolio[2]
        if ticker not in portfolio_data:
            portfolio_data[ticker] = {
                'ticker': ticker,
                'shares': portfolio[3],
                'total_purchase_value': portfolio[3] * portfolio[4],
                'average_purchase_price': portfolio[4],
                'purchases': [],  # Initialize list to store purchase history
                # You can add more fields here if needed
            }
        else:
            portfolio_data[ticker]['shares'] += portfolio[3]
            portfolio_data[ticker]['total_purchase_value'] += portfolio[3] * portfolio[4]
            portfolio_data[ticker]['average_purchase_price'] = (portfolio_data[ticker]['average_purchase_price'] + portfolio[4]) / 2
        
        # Append purchase details to the purchases list
        portfolio_data[ticker]['purchases'].append({
            'shares': portfolio[3],
            'purchase_price': portfolio[4],
            'purchase_date': portfolio[5]
        })

    # Calculate the cumulative value for each ticker and format values to 2 decimal places
    for ticker_data in portfolio_data.values():
        today = datetime.today().strftime('%Y-%m-%d')
        current_price = get_price_on_date(ticker_data['ticker'], today)
        if current_price is not None:
            ticker_data['current_value'] = round(ticker_data['shares'] * current_price, 2)
            ticker_data['total_purchase_value'] = round(ticker_data['total_purchase_value'], 2)
            ticker_data['average_purchase_price'] = round(ticker_data['average_purchase_price'], 2)
        else:
            ticker_data['current_value'] = None
            ticker_data['total_purchase_value'] = None
            ticker_data['average_purchase_price'] = None

    return render_template('portfolio.html', portfolio_data=list(portfolio_data.values()))











def get_price_on_date(ticker, date):
    stock = yf.Ticker(ticker)
    start_date = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)
    end_date = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)
    data = stock.history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))
    if data.empty or 'Close' not in data.columns:
        return None  # No data available
    return data['Close'].iloc[0]  # Assuming you want the closing price of the first day available



def add_stock_to_portfolio():
    ticker = request.form.get('ticker')
    shares = request.form.get('shares')
    purchase_date = request.form.get('purchase_date')

    # Ensure all fields are provided
    if not all([ticker, shares, purchase_date]):
        flash('All fields are required.')
        return redirect(url_for('manage_portfolio'))

    price = get_price_on_date(ticker, purchase_date)
    if price is None:
        flash("Price data not available for the given date.")
        return redirect(url_for('manage_portfolio'))

    user_id = session['user_id']
    conn = connect_db()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO Portfolio (user_id, ticker, shares, purchase_price, purchase_date) VALUES (?, ?, ?, ?, ?)',
                  (user_id, ticker, float(shares), price, purchase_date))
        conn.commit()
        flash('Stock added successfully!')
    except Exception as e:
        flash(f"An error occurred: {e}")
    finally:
        conn.close()
    return redirect(url_for('manage_portfolio'))


@app.route('/portfolio', methods=['GET', 'POST'])
def manage_portfolio():
    if 'user_id' not in session:
        flash("You need to login first")
        return redirect(url_for('login'))

    if request.method == 'POST':
        return add_stock_to_portfolio()
    else:
        return display_portfolio()


def open_browser():
    webbrowser.open_new('http://127.0.0.1:5000/')


def create_line_plot(user_ticker, user_ticker_company_name):
    x = user_ticker['Date']
    y = user_ticker['Close']
    df = pd.DataFrame({'x': x, 'y': y})  # creating a sample dataframe

    trace = go.Scatter(
        x=df['x'],
        y=df['y'],
        mode='lines',
        name=user_ticker_company_name
    )

    data = [trace]

    graphJSON = json.dumps(data, cls=plotly.utils.PlotlyJSONEncoder)
    return graphJSON


def create_candlestick_plot(user_ticker, user_ticker_company_name):
    df = user_ticker

    trace = go.Candlestick(
        x=df['Date'],
        open=df['Open'],
        high=df['High'],
        low=df['Low'],
        close=df['Close'],
        name=user_ticker_company_name
    )

    data = [trace]

    graphJSON = json.dumps(data, cls=plotly.utils.PlotlyJSONEncoder)
    return graphJSON


def create_macd_plot(user_ticker, user_ticker_company_name):
    df = user_ticker

    x = user_ticker['Date']
    y = user_ticker['Close']
    df = pd.DataFrame({'x': x, 'y': y})
    exp1 = user_ticker['Close'].ewm(span=12, adjust=False).mean()
    exp2 = user_ticker['Close'].ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    exp3 = macd.ewm(span=9, adjust=False).mean()
    macdh = macd - exp3
    trace0 = go.Bar(
        x=df['x'],
        y=macdh,
        name=user_ticker_company_name
    )
    trace1 = go.Scatter(
        x=df['x'],
        y=macd,
        mode='lines',
        name='MACD Line'
    )
    trace2 = go.Scatter(
        x=df['x'],
        y=exp3,
        mode='lines',
        name='Signal Line'
    )

    data = [trace0, trace1, trace2]

    graphJSON = json.dumps(data, cls=plotly.utils.PlotlyJSONEncoder)
    return graphJSON


def create_moving_average_plot(user_ticker, user_ticker_company_name):
    # Check if the DataFrame is empty
    if user_ticker.empty:
        print("No data available in DataFrame.")
        return None, None

    # Your existing code to calculate moving averages
    x = user_ticker['Date']
    y = user_ticker['Close']
    df = pd.DataFrame({'x': x, 'y': y})
    rolling_mean = df.y.rolling(window=30).mean()
    rolling_mean2 = df.y.rolling(window=60).mean()

    trace0 = go.Scatter(x=df['x'], y=df['y'], mode='lines', name=user_ticker_company_name)
    trace1 = go.Scatter(x=df['x'], y=rolling_mean, mode='lines', name='30 Day MA')
    trace2 = go.Scatter(x=df['x'], y=rolling_mean2, mode='lines', name='60 Day MA')
    data = [trace0, trace1, trace2]

    # Handle cases where no rolling mean data is available
    if rolling_mean.empty:
        average = None
    else:
        average = round(rolling_mean.iloc[-1], 2) if not pd.isna(rolling_mean.iloc[-1]) else None

    graphJSON = json.dumps(data, cls=plotly.utils.PlotlyJSONEncoder)
    return average, graphJSON


def create_rsi_plot(user_ticker, user_ticker_company_name):
    # Check if DataFrame is empty
    if user_ticker.empty:
        print("No data available in user_ticker DataFrame.")
        return None, None  # Return None or appropriate defaults

    # Calculate RSI
    delta = user_ticker['Close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=13, adjust=False).mean()
    ema_down = down.ewm(com=13, adjust=False).mean()
    rsi = ema_up / ema_down
    user_ticker['RSI'] = 100 - (100 / (1 + rsi))

    if 'RSI' not in user_ticker or user_ticker['RSI'].isnull().all():
        print("RSI calculation failed or no valid data in RSI column.")
        return None, None

    # Ensure there's at least one non-NaN RSI value
    if user_ticker['RSI'].dropna().empty:
        print("No non-NaN RSI values available.")
        return None, None

    x = user_ticker['Date']
    y = user_ticker['RSI']

    trace1 = go.Scatter(
        x=x,
        y=y,
        mode='lines',
        name='RSI'
    )
    trace2 = go.Scatter(
        x=x,
        y=[30] * len(x),
        line=dict(dash='dash'),
        name='Over Sold'
    )
    trace3 = go.Scatter(
        x=x,
        y=[70] * len(x),
        line=dict(dash='dash'),
        name='Over Bought'
    )

    rsi_last = round(user_ticker['RSI'].dropna().iloc[-1], 2) if not user_ticker['RSI'].dropna().empty else None

    data = [trace1, trace3, trace2]
    graphJSON = json.dumps(data, cls=plotly.utils.PlotlyJSONEncoder)
    return rsi_last, graphJSON



def create_comparison_plot(user_ticker, spy_ticker, user_ticker_company_name, spy_ticker_company_name):
    x0 = user_ticker['Date']
    y0 = user_ticker['Close']
    df0 = pd.DataFrame({'x': x0, 'y': y0})

    x1 = spy_ticker['Date']
    y1 = spy_ticker['Close']
    df1 = pd.DataFrame({'x': x1, 'y': y1})

    trace0 = go.Scatter(
        x=df0['x'],
        y=df0['y'],
        mode='lines',
        name=user_ticker_company_name
    )
    trace1 = go.Scatter(
        x=df1['x'],
        y=df1['y'],
        mode='lines',
        name=spy_ticker_company_name
    )

    data = [trace0, trace1]

    graphJSON = json.dumps(data, cls=plotly.utils.PlotlyJSONEncoder)
    return graphJSON


def buy_or_sell(rsi):
    if (rsi <= 100) & (rsi > 65):
        return 'Bull Market - Recommended to Buy'
    elif (rsi <= 65) & (rsi > 55):
        return 'Bear Market - Recommended to Sell'
    elif (rsi <= 55) & (rsi > 35):
        return 'Bull Market - Recommended to Buy'
    elif (rsi <= 35) & (rsi > 0):
        return 'Bear Market - Recommended to Sell'


def get_info(ticker, start, end):
    stock = yf.Ticker(ticker)
    print(stock)
    try:
        if all([start, end]):
            data = stock.history(start=start, end=end)
        elif start == '' and end != '':
            data = stock.history(end=end, period="max")
        elif start != '' and end == '':
            data = stock.history(start=start)
        else:
            data = stock.history(period="max")

        if data.empty:
            return False, "No data found for ticker."

        data.reset_index(level=0, inplace=True)
        data.drop(['Dividends', 'Stock Splits'], axis='columns', inplace=True)
        company_name = stock.info.get('longName', "Unknown company name")
        return data, company_name
    except Exception as e:
        print(f"Error fetching info for ticker: {ticker}", e)
        return False, "Failed to retrieve data."



def write_to_db(data, user_id):
    conn = sqlite3.connect(r"pythonsqlite.db")
    try:
        
        data['user_id'] = user_id  # This assigns the user_id to all rows in the DataFrame
        # Save the DataFrame to SQL
        data.to_sql('Stock', conn, if_exists='replace', index=False, method="multi")

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        conn.close()




def read_from_db(user_id):
    conn = sqlite3.connect('pythonsqlite.db')
    query = "SELECT Date, Open, High, Low, Close, Volume FROM Stock WHERE user_id=?"
    user_ticker = pd.read_sql(query, conn, params=(user_id,))
    conn.close()
    return user_ticker




def read_dates_from_db(user_id=None):
    conn = sqlite3.connect(r"pythonsqlite.db")
    try:
        if user_id is not None:
            query_start = "SELECT Date FROM Stock WHERE user_id = ? ORDER BY Date LIMIT 1"
            query_end = "SELECT Date FROM Stock WHERE user_id = ? ORDER BY Date DESC LIMIT 1"
            start = pd.read_sql(query_start, conn, params=(user_id,))['Date'].iloc[0].split()[0]
            end = pd.read_sql(query_end, conn, params=(user_id,))['Date'].iloc[0].split()[0]
        else:
            start = pd.read_sql('SELECT Date FROM Stock ORDER BY Date LIMIT 1', conn)['Date'].iloc[0].split()[0]
            end = pd.read_sql('SELECT Date FROM Stock ORDER BY Date DESC LIMIT 1', conn)['Date'].iloc[0].split()[0]
    except Exception as e:
        print(f"Error accessing database: {e}")
        start, end = None, None  # Provide defaults or handle as appropriate
    finally:
        conn.close()
    return start, end




def increase_date_by_1(date):
    if date is None:
        return None  # Return None or a default date as appropriate
    datetime_object = datetime.strptime(date, '%Y-%m-%d')
    datetime_object += timedelta(days=1)
    return datetime_object.strftime('%Y-%m-%d')



if __name__ == '__main__':
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        Timer(1, webbrowser.open, ['http://127.0.0.1:5000/']).start()
    app.run(debug=True)