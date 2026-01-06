import csv
import os
from datetime import datetime
from breeze_connect import BreezeConnect  # type: ignore
import app_config as config

class BreezeClient:
    """
    A wrapper class for the ICICI Breeze API to handle authentication 
    and order placement with support for PAPER vs LIVE modes.
    """

    def __init__(self):
        """
        Initialize the BreezeConnect client and authenticate if in LIVE mode.
        """
        self.breeze = BreezeConnect(api_key=config.API_KEY)
        
        # In a real scenario, you usually need to generate a session token 
        # via a web flow or use a pre-generated one.
        # Authenticate with the API to enable data fetching (Websocket/History)
        # We need this even for PAPER mode to get live ticks.
        try:
            self.breeze.generate_session(
                api_secret=config.SECRET_KEY, 
                session_token=config.SESSION_TOKEN
            )
            print("[INFO] Connected to ICICI Direct Breeze API")
        except Exception as e:
            print(f"[ERROR] Failed to connect to Breeze API: {e}")

        if config.TRADING_MODE == "PAPER":
            print("[INFO] Running in PAPER TRADING mode. Orders will be simulated.")

    def place_order(self, stock_code: str, action: str, quantity: int, price: float = 0.0, 
                    product_type: str = "options", right: str = "", strike_price: str = "", expiry_date: str = ""):
        """
        Place an order for NIFTY Options.

        Args:
            stock_code (str): The symbol token or stock code.
            action (str): "buy" or "sell".
            quantity (int): Number of shares/lots.
            price (float): The price at which the order is simulated (for paper trade).
            product_type (str): "options", "futures", "cash".
            right (str): "Call" or "Put" (or "others" for cash).
            strike_price (str): Strike price for options.
            expiry_date (str): Expiry date (e.g., "2025-01-02").
        """
        if config.TRADING_MODE == "LIVE":
            try:
                # Example order placement - specific to Breeze API signature
                response = self.breeze.place_order(
                    stock_code=stock_code,
                    exchange_code="NFO",
                    product=product_type,
                    action=action.lower(),
                    order_type="market",
                    stoploss="",
                    quantity=str(quantity),
                    price="",
                    validity="day",
                    validity_date=datetime.now().strftime("%Y-%m-%dT06:00:00.000Z"),
                    disclosed_quantity="0",
                    expiry_date=f"{expiry_date}T06:00:00.000Z" if expiry_date else "",
                    right=right.lower(),
                    strike_price=strike_price
                )
                print(f"[LIVE] Order Placed: {response}")
            except Exception as e:
                print(f"[ERROR] Order execution failed: {e}")
        
        elif config.TRADING_MODE == "PAPER":
            self._log_paper_trade(stock_code, action, quantity, price, right, strike_price)

    def get_positions(self) -> list:
        """
        Fetch current positions from broker and return in normalized format.
        
        Returns:
            List of position dicts with standardized structure:
            [
                {
                    'symbol': str,          # e.g., 'NIFTY'
                    'expiry_date': str,     # e.g., '2025-01-09'
                    'strike_price': float,  # e.g., 22500.0
                    'right': str,           # 'Call' or 'Put'
                    'quantity': int         # negative = short, positive = long
                },
                ...
            ]
        
        Behavior:
            - PAPER mode: Always returns [] (no simulated positions)
            - LIVE mode: Calls Breeze API get_portfolio_positions() and normalizes
            - On error: Returns [] (does not raise)
        
        Normalization:
            - Quantity: SELL/SHORT → negative, BUY/LONG → positive
            - Right: Normalized to 'Call' or 'Put' (title case)
            - Symbol: Uppercase, consistent naming
            - Only returns derivative positions (options/futures)
        
        Breeze API Notes:
            TODO: Verify exact method name (may be get_portfolio_positions, 
            get_positions, or get_holdings). Response structure varies.
            
            Expected Breeze response fields (approximate):
            - stock_code or symbol
            - expiry_date (may need parsing)
            - strike_price
            - right ('CE' → 'Call', 'PE' → 'Put')
            - buy_quantity / sell_quantity (or net_quantity with sign)
        """
        if config.TRADING_MODE == "PAPER":
            # Paper mode: No broker positions to fetch
            return []
        
        # LIVE mode: Fetch from broker
        try:
            # Attempt to call Breeze API for positions
            # Method name may vary: get_portfolio_positions, get_positions, etc.
            
            # Try the most common method name first
            if hasattr(self.breeze, 'get_portfolio_positions'):
                response = self.breeze.get_portfolio_positions()
            elif hasattr(self.breeze, 'get_positions'):
                response = self.breeze.get_positions()
            else:
                # Fallback: method doesn't exist
                print("[WARN] Breeze API position fetch method not found. Returning empty.")
                return []
            
            # Check response structure
            if not response or 'Success' not in response:
                print("[WARN] Broker position fetch returned empty or error.")
                return []
            
            positions_data = response.get('Success', [])
            if not positions_data:
                # No open positions
                return []
            
            # Normalize positions
            normalized = []
            for pos in positions_data:
                # Filter: only derivatives (options/futures)
                product_type = pos.get('product_type', '').lower()
                if product_type not in ['options', 'futures']:
                    continue
                
                # Extract fields with defensive defaults
                symbol = pos.get('stock_code', pos.get('symbol', 'UNKNOWN')).upper()
                expiry = pos.get('expiry_date', '')
                strike = float(pos.get('strike_price', 0.0))
                right_raw = pos.get('right', '').upper()
                
                # Normalize right: CE/CALL → 'Call', PE/PUT → 'Put'
                if right_raw in ['CE', 'CALL']:
                    right = 'Call'
                elif right_raw in ['PE', 'PUT']:
                    right = 'Put'
                else:
                    # Skip non-option positions (futures, etc.)
                    continue
                
                # Quantity with sign convention
                # Breeze may provide buy_quantity, sell_quantity, or net_quantity
                buy_qty = int(pos.get('buy_quantity', 0))
                sell_qty = int(pos.get('sell_quantity', 0))
                
                # Net quantity: positive = long, negative = short
                net_qty = buy_qty - sell_qty
                
                if net_qty == 0:
                    # Closed position, skip
                    continue
                
                normalized.append({
                    'symbol': symbol,
                    'expiry_date': expiry,
                    'strike_price': strike,
                    'right': right,
                    'quantity': net_qty
                })
            
            return normalized
            
        except Exception as e:
            print(f"[ERROR] Failed to fetch broker positions: {e}")
            # Do not raise - return empty list for safety
            return []

    def _log_paper_trade(self, stock_code: str, action: str, quantity: int, price: float, right: str, strike_price: str):
        """
        Log paper trades to a CSV file.
        """
        file_path = "paper_trades.csv"
        file_exists = os.path.isfile(file_path)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(file_path, mode="a", newline="") as file:
            writer = csv.writer(file)
            # Write header if new file
            if not file_exists:
                writer.writerow(["Timestamp", "Symbol", "Action", "Quantity", "Price", "Right", "Strike"])
            
            writer.writerow([timestamp, stock_code, action, quantity, price, right, strike_price])
        
        # Log simulation message (product_type assumed "options" for derivatives)
        if right and strike_price:
            print(f"[SIMULATION] {action.upper()}ING {strike_price} {right} at NIFTY price {price}")
        else:
            print(f"[SIMULATION] {action.title()} Order Executed for {stock_code} at {price}")
