from stock_ai.backtest import run_backtest
if __name__=="__main__":
    out,s=run_backtest(); print(out.tail(10).to_string(index=False)); print(s)
