from datetime import date

history = [
    {"date": date(2026, 3, 1), "quantity": 23}, # Пн
    {"date": date(2026, 3, 2), "quantity": 22}, # Вт
    {"date": date(2026, 3, 3), "quantity": 21}, # Ср
    {"date": date(2026, 3, 4), "quantity": 17}, # Чт (ошибка, 21-17 = расход 4)
    {"date": date(2026, 3, 5), "quantity": 19}, # Пт (исправление, 17-19 = расход -2)
    {"date": date(2026, 3, 6), "quantity": 17}, # Суб
    {"date": date(2026, 3, 7), "quantity": 14}, # Вск
]
supplies = [] # no supplies in this example
total_consumed_qty = 0.0
total_valid_days = 0

print("Tracing calculation:")
for i in range(len(history) - 1):
    cur_rec = history[i]
    nxt_rec = history[i+1]
    
    days_between = (nxt_rec['date'] - cur_rec['date']).days
    if days_between <= 0: continue
    
    if cur_rec['quantity'] <= 0 and nxt_rec['quantity'] <= 0:
        continue
        
    gap_supplies_qty = sum(s['boxes'] for s in supplies if cur_rec['date'] < s['date'] <= nxt_rec['date'])
    consumed_qty = cur_rec['quantity'] + gap_supplies_qty - nxt_rec['quantity']
    
    print(f"  Step {cur_rec['date']} -> {nxt_rec['date']} ({days_between} days): Start={cur_rec['quantity']}, End={nxt_rec['quantity']}, Consumed={consumed_qty}")
    
    total_valid_days += days_between
    total_consumed_qty += consumed_qty

print("\nFinal Result:")
if total_valid_days > 0:
    print(f"Total Consumed: {total_consumed_qty} over {total_valid_days} valid days = {round(total_consumed_qty / total_valid_days, 2)} per day")
else:
    print("No valid days.")
