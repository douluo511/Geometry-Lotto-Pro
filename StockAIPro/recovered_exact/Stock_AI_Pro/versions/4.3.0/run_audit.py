from stock_ai.audit import run_audit
if __name__=="__main__":
    r=run_audit(); print("MODEL TRUST:",r["trust"])
    [print(c["status"],"-",c["name"],"-",c["detail"]) for c in r["checks"]]
