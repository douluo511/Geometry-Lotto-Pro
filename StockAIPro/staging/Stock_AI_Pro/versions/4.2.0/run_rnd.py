from stock_ai.rnd import run_rnd_cycle
if __name__=='__main__':
    r=run_rnd_cycle();print('R&D STATUS:',r.get('status'))
