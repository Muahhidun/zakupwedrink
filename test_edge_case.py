from datetime import date, timedelta

history = [
    {"date": date(2026, 3, 1), "quantity": 3},  # Пн
    {"date": date(2026, 3, 2), "quantity": 3},  # Вт
    {"date": date(2026, 3, 3), "quantity": 3},  # Ср
    {"date": date(2026, 3, 4), "quantity": 3},  # Чт
    # Пт пропустили 
    {"date": date(2026, 3, 6), "quantity": 2},  # Суб
    {"date": date(2026, 3, 7), "quantity": 2},  # Вск
    {"date": date(2026, 3, 8), "quantity": 1},  # Пн
    {"date": date(2026, 3, 9), "quantity": 1},  # Вт
    {"date": date(2026, 3, 10), "quantity": 1}, # Ср
    {"date": date(2026, 3, 11), "quantity": 0}, # Чт
    {"date": date(2026, 3, 12), "quantity": 0}, # Пт
    {"date": date(2026, 3, 13), "quantity": 0}, # Суб
    {"date": date(2026, 3, 14), "quantity": 0}, # Вск
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
    
    # zero check
    if cur_rec['quantity'] <= 0 and nxt_rec['quantity'] <= 0:
        print(f"  Skipped zero gap: {cur_rec['date']} -> {nxt_rec['date']} ({days_between} days)")
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
