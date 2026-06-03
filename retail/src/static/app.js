  (function(){
    "use strict";

    // ---- Session id + lock-aware fetch ----
    // One id per browser tab, persisted across reloads (sessionStorage) so the
    // same person can reload without losing their own lease for 90s.
    let SESSION_ID = (typeof sessionStorage !== "undefined") && sessionStorage.getItem("raif_session_id");
    if (!SESSION_ID) {
      SESSION_ID = (window.crypto && crypto.randomUUID && crypto.randomUUID())
                 || ("s-" + Math.random().toString(36).slice(2) + Date.now().toString(36));
      try { sessionStorage.setItem("raif_session_id", SESSION_ID); } catch (e) {}
    }
    const _origFetch = window.fetch.bind(window);
    window.fetch = function(url, opts) {
      opts = opts || {};
      opts.headers = Object.assign({}, opts.headers || {}, { "X-Session-Id": SESSION_ID });
      return _origFetch(url, opts);
    };

    // ---- Profile lock state ----
    let lockedClientId = null;        // client we hold the lease on
    let heartbeatTimer = null;
    let lockBlocked = false;          // true when another session holds it

    async function acquireLock(clientId, holderLabel) {
      try {
        const r = await fetch("/api/lock/acquire", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ client_id: clientId, holder_label: holderLabel || "" }),
        });
        if (r.ok) {
          lockedClientId = clientId;
          lockBlocked = false;
          startHeartbeat();
          renderLockBanner(null);
          setActionsDisabled(false);
          return true;
        }
        // 423 — someone else holds it
        const info = await r.json().catch(() => ({}));
        lockedClientId = null;
        lockBlocked = true;
        stopHeartbeat();
        renderLockBanner(info);
        setActionsDisabled(true);
        return false;
      } catch (e) {
        // Server unreachable — fail open so the demo keeps working
        lockedClientId = clientId;
        lockBlocked = false;
        renderLockBanner(null);
        setActionsDisabled(false);
        return true;
      }
    }

    async function releaseLock() {
      if (!lockedClientId) return;
      const cid = lockedClientId;
      lockedClientId = null;
      stopHeartbeat();
      try {
        await fetch("/api/lock/release", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ client_id: cid }),
        });
      } catch (e) {}
    }

    function startHeartbeat() {
      stopHeartbeat();
      heartbeatTimer = setInterval(() => {
        if (!lockedClientId) return;
        fetch("/api/lock/heartbeat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ client_id: lockedClientId }),
        }).catch(() => {});
      }, 30000);
    }
    function stopHeartbeat() {
      if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
    }

    // Best-effort release when the tab closes.
    window.addEventListener("beforeunload", () => {
      if (lockedClientId && navigator.sendBeacon) {
        const data = new Blob(
          [JSON.stringify({ client_id: lockedClientId })],
          { type: "application/json" },
        );
        navigator.sendBeacon("/api/lock/release", data);
      }
    });

    function renderLockBanner(info) {
      const el = document.getElementById("lock-banner");
      if (!el) return;
      if (!info) { el.innerHTML = ""; el.style.display = "none"; return; }
      const heldBy = info.held_by || "another session";
      const wait = info.expires_in != null ? ` (~${info.expires_in}s)` : "";
      el.innerHTML = `
        <div class="lock-card">
          <div class="lock-icon">🔒</div>
          <div class="lock-text">
            <b>${t("locked_title")}</b>
            <div>${t("locked_body")} — ${heldBy}${wait}.</div>
          </div>
          <button class="link-btn" id="lock-retry">${t("locked_retry")}</button>
        </div>`;
      el.style.display = "block";
      const retry = document.getElementById("lock-retry");
      if (retry) retry.addEventListener("click", () => {
        const opt = sel.selectedOptions[0];
        if (opt) acquireLock(opt.value, opt.dataset.name || "");
      });
    }

    function setActionsDisabled(disabled) {
      document.querySelectorAll(
        '.phone form button[type="submit"], .phone .btn.primary, .phone .link-btn'
      ).forEach(b => {
        // Don't disable the lock banner's own retry button
        if (b.id === "lock-retry") return;
        b.disabled = disabled;
        b.classList.toggle("is-locked", disabled);
      });
    }

    // ---- Bottom-nav registry ----
    // To add a feature: add an entry here, a matching <div class="tab-pane"
    // data-pane="KEY">, an i18n label, and (optionally) a per-tab loader below.
    const ICON = (paths) =>
      `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ` +
      `stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
    const TAB_DEFS = [
      { key: "transfers",  i18n: "transfers_tab",
        icon: ICON('<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.7V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.7"/>') },
      { key: "card",       i18n: "card_tab",
        icon: ICON('<rect x="2.5" y="5" width="19" height="14" rx="3"/><path d="M2.5 9.5h19"/>') },
      { key: "creditcard", i18n: "cc_tab",
        icon: ICON('<path d="M12 3 21 9l-9 12L3 9z"/><path d="M3 9h18"/>') },
      { key: "savings",    i18n: "savings_tab",
        icon: ICON('<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><circle cx="12" cy="12" r="3.3"/><path d="M12 8.7V6.5M12 17.5v-2.2"/>') },
      { key: "invest",     i18n: "invest_tab",
        icon: ICON('<path d="M3 17l6-6 4 4 7-7"/><path d="M17 8h4v4"/>') },
      { key: "brokerage",  i18n: "brokerage_tab",
        icon: ICON('<path d="M4 20V11M9 20V5M14 20V14M19 20V8"/>') },
      { key: "loans",      i18n: "loans_tab",
        icon: ICON('<circle cx="7.5" cy="7.5" r="2.4"/><circle cx="16.5" cy="16.5" r="2.4"/><path d="M18.5 5.5 5.5 18.5"/>') },
      { key: "carloan",    i18n: "carloan_tab",
        icon: ICON('<path d="M5 13l1.6-4.5C6.8 8 7.3 7.5 8 7.5h8c.7 0 1.2.5 1.4 1L19 13"/><path d="M3.8 13h16.4v4.5H3.8z"/><circle cx="7.5" cy="17.5" r="1.6"/><circle cx="16.5" cy="17.5" r="1.6"/>') },
      { key: "mortgage",   i18n: "mortgage_tab",
        icon: ICON('<path d="M3 11 12 4l9 7"/><path d="M5 10.5V20h5v-5h4v5h5v-9.5"/><circle cx="14.5" cy="13" r="1"/>') },
      { key: "invite",     i18n: "invite_tab",
        icon: ICON('<circle cx="8.5" cy="9" r="3"/><path d="M3 19.5c.7-3 3-4.5 5.5-4.5s4.8 1.5 5.5 4.5"/><circle cx="17" cy="8" r="2.2"/><path d="M14.6 13.6c.7-.4 1.5-.6 2.4-.6 1.9 0 3.3 1 4 3"/>') },
    ];

    // ---- i18n ----
    const i18n = {
      ru: {
        balance_label:    "остаток на счёте",
        profile:          "Профиль",
        transfers_tab:    "Переводы",
        card_tab:         "Карта",
        cc_tab:           "Кредитная",
        loans_tab:        "Кредиты",
        transfer_title:   "Перевести",
        to_label:         "Кому",
        to_placeholder:   "имя или ID получателя",
        amount_label:     "Сумма, ₽",
        transfer_btn:     "Перевести",
        recent_ops:       "Последние операции",
        no_ops:           "Операций пока нет",
        load_fail:        "Не удалось загрузить операции",
        fill_fields:      "введи получателя и сумму",
        insufficient_funds: "Недостаточно средств на счёте",
        amount_below_min: "Сумма меньше минимальной",
        overpay_debt:     "Сумма больше задолженности",
        sent:             "Отправлено",
        recipient:        "получатель",
        bank_client:      "клиент банка",
        external:         "внешний счёт",
        error:            "ошибка",
        server_down:      "сервер не ответил",
        transfer_in:      "Перевод входящий",
        transfer_out:     "Перевод исходящий",
        card_purchase:    "Оплата картой",
        atm_withdraw:     "Снятие в банкомате",
        salary:           "Зарплата",
        utility_payment:  "Коммунальные",
        toggle_label:     "EN",
        choose_product:   "Выберите продукт",
        loading_products: "Загрузка продуктов...",
        no_products:      "Продукты пока недоступны",
        rate_label:       "Ставка",
        loan_amount_title:"Сумма кредита",
        desired_amount:   "Желаемая сумма, ₽",
        apply_btn:        "Подать заявку",
        fill_amount:      "Укажите сумму кредита",
        approved:         "Одобрено!",
        declined:         "Отказано",
        approved_detail:  "Ваша заявка одобрена. Максимальная сумма",
        declined_detail:  "К сожалению, заявка отклонена",
        reason_label:     "Причина",
        products_error:   "Не удалось загрузить продукты",
        loading_card:     "Загрузка карты...",
        card_error:       "Не удалось загрузить данные карты",
        debit_card:       "ДЕБЕТОВАЯ",
        cashback_earned:  "Кешбэк",
        cashback_rate:    "Базовая ставка",
        cashback_history: "Кешбэк по операциям",
        no_cashback:      "Нет операций с кешбэком",
        cb_groceries:     "Продукты",
        cb_transport:     "Транспорт",
        cb_other:         "Прочее",
        your_segment:     "Ваш сегмент",
        savings_tab:      "Вклады",
        loading_savings:  "Загрузка вкладов...",
        savings_error:    "Не удалось загрузить данные о вкладах",
        your_savings:     "Ваши накопления",
        interest_earned:  "Начислено процентов",
        available_deposits: "Доступные вклады",
        no_deposit_products: "Вклады пока недоступны",
        per_year:         "годовых",
        open_deposit:     "Открыть вклад",
        deposit_amount:   "Сумма вклада, ₽",
        deposit_term:     "Срок, месяцев",
        deposit_open_btn: "Открыть",
        deposit_fill:     "Укажите сумму вклада",
        deposit_success:  "Вклад открыт!",
        estimated_income: "Ожидаемый доход",
        your_deposits:    "Ваши вклады",
        no_deposits:      "У вас пока нет вкладов",
        months:           "мес.",
        matures_at:       "Дата погашения",
        flexible:         "Снятие в любое время",
        deposit_maturity: "Погашение",
        invest_tab:       "Инвестиции",
        loading_invest:   "Загрузка инвестиций...",
        invest_error:     "Не удалось загрузить инвестиции",
        portfolio_value:  "Стоимость портфеля",
        your_portfolio:   "Ваш портфель",
        no_holdings:      "У вас пока нет инвестиций",
        available_instruments: "Доступные инструменты",
        no_instruments:   "Инструменты пока недоступны",
        exp_return:       "Ожид. доходность",
        risk_low:         "низкий риск",
        risk_medium:      "средний риск",
        risk_high:        "высокий риск",
        invest_now:       "Инвестировать",
        invest_amount:    "Сумма инвестиции, ₽",
        invest_btn:       "Купить",
        tap_to_invest:    "Нажмите, чтобы выбрать",
        invest_fill:      "Укажите сумму инвестиции",
        invest_success:   "Заявка принята!",
        projected_1y:     "Прогноз через год",
        brokerage_tab:    "Брокер",
        loading_brokerage: "Загрузка брокеража...",
        brokerage_error:  "Не удалось загрузить брокеридж",
        mortgage_tab:     "Ипотека",
        loading_mortgage: "Загрузка ипотеки...",
        mortgage_error:   "Не удалось загрузить ипотеку",
        mortgage_title:   "Ипотечный калькулятор",
        property_price:   "Стоимость недвижимости, ₽",
        down_payment:     "Первоначальный взнос, ₽",
        term_years:       "Срок, лет",
        years_short:      "лет",
        loan_amount:      "Сумма кредита",
        monthly_payment:  "Ежемесячный платёж",
        total_to_pay:     "Всего к выплате",
        ltv_label:        "LTV",
        dti_label:        "DTI",
        rate_label_short: "Ставка",
        get_quote:        "Рассчитать",
        apply_mortgage:   "Подать заявку",
        approved_mortgage: "Заявка одобрена",
        declined_mortgage: "Заявка отклонена",
        your_mortgages:   "Ваши ипотеки",
        no_mortgages:     "У вас пока нет ипотек",
        mortgage_intro:   "Рассчитайте платёж, и мы подберём подходящие условия.",
        fill_mortgage:    "Заполните стоимость, взнос и срок",
        trading_cash:     "Свободные средства",
        positions_value:  "Стоимость позиций",
        your_positions:   "Ваши позиции",
        no_positions:     "У вас пока нет позиций",
        market:           "Рынок",
        no_securities:    "Бумаги недоступны",
        trade_buy:        "Купить",
        trade_sell:       "Продать",
        quantity:         "Количество",
        est_total:        "Примерно",
        commission_label: "Комиссия",
        order_done:       "Заявка исполнена",
        not_enough_units: "Недостаточно бумаг для продажи",
        qty_required:     "Укажите количество",
        units:            "шт.",
        tap_to_trade:     "Нажмите для сделки",
        order_rejected:   "Заявка отклонена",
        invested:         "Вложено",
        for_you:          "Для вас",
        offer_cta:        "Подробнее",
        withdraw:         "Снять",
        withdrawn:        "Снято",
        principal:        "Основной долг",
        interest:         "Проценты",
        closed:           "Закрыт",
        withdraw_confirm: "Закрыть вклад и вернуть средства на счёт?",
        withdraw_confirm_early: "Это срочный вклад. При досрочном снятии проценты будут уменьшены. Продолжить?",
        cashback_balance: "Доступный кешбэк",
        redeem_cashback:  "Перевести кешбэк на счёт",
        redeem_prompt:    "Сколько кешбэка перевести?",
        redeem_invalid:   "Неверная сумма",
        redeem_ok:        "Кешбэк зачислен на счёт",
        locked_title:     "Профиль занят",
        locked_body:      "Сейчас с этим клиентом работает",
        locked_retry:     "Повторить",
        invite_tab:       "Друзья",
        home_tab:         "Главная",
        cards_tab:        "Карты",
        wealth_tab:       "Капитал",
        borrow_tab:       "Займы",
        friends_tab:      "Друзья",
        debit_short:      "Дебетовая",
        credit_short:     "Кредитная",
        carloan_tab:      "Автокредит",
        loading_carloan:  "Загрузка автокредита...",
        carloan_title:    "Калькулятор автокредита",
        car_price:        "Стоимость автомобиля, ₽",
        car_intro:        "Рассчитайте платёж и подайте заявку на покупку авто.",
        approved_carloan: "Автокредит одобрен",
        declined_carloan: "Автокредит отклонён",
        your_carloans:    "Ваши автокредиты",
        loading_invite:   "Загрузка приглашений...",
        invite_title:     "Приведи друга",
        invite_subtitle:  "Поделитесь кодом — оба получите бонус",
        your_code:        "Ваш код",
        copy_code:        "Скопировать",
        copied:           "Скопировано!",
        share:            "Поделиться",
        share_subject:    "Self-Driving Raif — приглашение",
        bonus_each:       "Бонус для каждого",
        invited_friends:  "Приглашённые друзья",
        no_invited:       "Вы пока никого не приглашали",
        invited_by_label: "Вас пригласил",
        enter_code_title: "У вас есть код друга?",
        enter_code_label: "Введите код",
        redeem_btn:       "Применить",
        invite_ok:        "Бонус активирован",
        invite_paid:      "Бонус начислен",
        invite_pending:   "Бонус будет начислен позже",
        invite_err_code_required: "Введите код",
        invite_err_self:  "Нельзя использовать свой код",
        invite_err_invalid: "Код не найден",
        invite_err_used:  "Вы уже использовали код",
        invite_err_not_allowed: "Использование кода не разрешено",
        total_bonus:      "Заработано на приглашениях",
        investor_profile_label: "Инвестиционный профиль",
        not_suitable:     "Не подходит вашему профилю",
        min_investment:   "Минимум",
        unsuitable_title: "Этот инструмент вам не подходит",
        suitable_alts:    "Подходящие альтернативы",
        loading_cc:       "Загрузка кредитной карты...",
        cc_error:         "Не удалось загрузить данные кредитной карты",
        credit_card:      "КРЕДИТНАЯ",
        cc_limit:         "Лимит",
        cc_owed:          "Задолженность",
        cc_available:     "Доступно",
        cc_min_payment:   "Мин. платёж",
        cc_interest:      "Процентная ставка",
        cc_grace:         "Льготный период",
        cc_days:          "дней",
        cc_pay_title:     "Погасить задолженность",
        cc_pay_amount:    "Сумма платежа, ₽",
        cc_pay_btn:       "Оплатить",
        cc_pay_success:   "Платёж принят",
        cc_not_eligible:  "Кредитная карта пока недоступна для данного клиента.",
        cc_fill_amount:   "Укажите сумму платежа",
        cc_used_of:       "использовано из",
        cc_secured:       "ЗАЩИЩЁННАЯ",
        cc_secured_note:  "Предложена защищённая кредитная карта",
      },
      en: {
        balance_label:    "account balance",
        profile:          "Profile",
        transfers_tab:    "Transfers",
        card_tab:         "Card",
        cc_tab:           "Credit",
        loans_tab:        "Loans",
        transfer_title:   "Send money",
        to_label:         "To",
        to_placeholder:   "name or recipient ID",
        amount_label:     "Amount, ₽",
        transfer_btn:     "Transfer",
        recent_ops:       "Recent transactions",
        no_ops:           "No transactions yet",
        load_fail:        "Could not load transactions",
        fill_fields:      "enter recipient and amount",
        insufficient_funds: "Insufficient funds on your account",
        amount_below_min: "Amount is below the minimum",
        overpay_debt:     "Amount exceeds the outstanding balance",
        sent:             "Sent",
        recipient:        "recipient",
        bank_client:      "bank client",
        external:         "external account",
        error:            "error",
        server_down:      "server did not respond",
        transfer_in:      "Incoming transfer",
        transfer_out:     "Outgoing transfer",
        card_purchase:    "Card purchase",
        atm_withdraw:     "ATM withdrawal",
        salary:           "Salary",
        utility_payment:  "Utilities",
        toggle_label:     "RU",
        choose_product:   "Choose a product",
        loading_products: "Loading products...",
        no_products:      "No products available yet",
        rate_label:       "Rate",
        loan_amount_title:"Loan amount",
        desired_amount:   "Desired amount, ₽",
        apply_btn:        "Apply for loan",
        fill_amount:      "Please enter a loan amount",
        approved:         "Approved!",
        declined:         "Declined",
        approved_detail:  "Your application is approved. Maximum amount",
        declined_detail:  "Unfortunately, your application was declined",
        reason_label:     "Reason",
        products_error:   "Could not load products",
        loading_card:     "Loading card...",
        card_error:       "Could not load card data",
        debit_card:       "DEBIT",
        cashback_earned:  "Cashback",
        cashback_rate:    "Base rate",
        cashback_history: "Cashback by transaction",
        no_cashback:      "No cashback transactions",
        cb_groceries:     "Groceries",
        cb_transport:     "Transport",
        cb_other:         "Other",
        your_segment:     "Your segment",
        savings_tab:      "Savings",
        loading_savings:  "Loading savings...",
        savings_error:    "Could not load savings data",
        your_savings:     "Your savings",
        interest_earned:  "Interest earned",
        available_deposits: "Available deposits",
        no_deposit_products: "No deposit products available yet",
        per_year:         "per year",
        open_deposit:     "Open a deposit",
        deposit_amount:   "Deposit amount, ₽",
        deposit_term:     "Term, months",
        deposit_open_btn: "Open",
        deposit_fill:     "Please enter a deposit amount",
        deposit_success:  "Deposit opened!",
        estimated_income: "Estimated income",
        your_deposits:    "Your deposits",
        no_deposits:      "You have no deposits yet",
        months:           "mo.",
        matures_at:       "Maturity date",
        flexible:         "Withdraw anytime",
        deposit_maturity: "Maturity",
        invest_tab:       "Invest",
        loading_invest:   "Loading investments...",
        invest_error:     "Could not load investments",
        portfolio_value:  "Portfolio value",
        your_portfolio:   "Your portfolio",
        no_holdings:      "You have no investments yet",
        available_instruments: "Available instruments",
        no_instruments:   "No instruments available yet",
        exp_return:       "Exp. return",
        risk_low:         "low risk",
        risk_medium:      "medium risk",
        risk_high:        "high risk",
        invest_now:       "Invest",
        invest_amount:    "Investment amount, ₽",
        invest_btn:       "Buy",
        tap_to_invest:    "Tap to select",
        invest_fill:      "Please enter an investment amount",
        invest_success:   "Order accepted!",
        projected_1y:     "1-year projection",
        brokerage_tab:    "Broker",
        loading_brokerage: "Loading brokerage...",
        brokerage_error:  "Could not load brokerage",
        mortgage_tab:     "Mortgage",
        loading_mortgage: "Loading mortgage...",
        mortgage_error:   "Could not load mortgage",
        mortgage_title:   "Mortgage calculator",
        property_price:   "Property price, ₽",
        down_payment:     "Down payment, ₽",
        term_years:       "Term, years",
        years_short:      "yrs",
        loan_amount:      "Loan amount",
        monthly_payment:  "Monthly payment",
        total_to_pay:     "Total to pay",
        ltv_label:        "LTV",
        dti_label:        "DTI",
        rate_label_short: "Rate",
        get_quote:        "Calculate",
        apply_mortgage:   "Apply for mortgage",
        approved_mortgage: "Approved",
        declined_mortgage: "Declined",
        your_mortgages:   "Your mortgages",
        no_mortgages:     "You have no mortgages yet",
        mortgage_intro:   "Calculate your payment and we'll find suitable terms.",
        fill_mortgage:    "Fill in price, down payment and term",
        trading_cash:     "Available cash",
        positions_value:  "Positions value",
        your_positions:   "Your positions",
        no_positions:     "You have no positions yet",
        market:           "Market",
        no_securities:    "No securities available",
        trade_buy:        "Buy",
        trade_sell:       "Sell",
        quantity:         "Quantity",
        est_total:        "Approx.",
        commission_label: "Commission",
        order_done:       "Order executed",
        not_enough_units: "Not enough units to sell",
        qty_required:     "Please enter a quantity",
        units:            "units",
        tap_to_trade:     "Tap to trade",
        order_rejected:   "Order rejected",
        invested:         "Invested",
        for_you:          "For you",
        offer_cta:        "Details",
        withdraw:         "Withdraw",
        withdrawn:        "Withdrew",
        principal:        "Principal",
        interest:         "Interest",
        closed:           "Closed",
        withdraw_confirm: "Close this deposit and return the funds to your account?",
        withdraw_confirm_early: "This is a fixed-term deposit. Early withdrawal will reduce the interest. Continue?",
        cashback_balance: "Cashback balance",
        redeem_cashback:  "Redeem cashback to balance",
        redeem_prompt:    "How much cashback to redeem?",
        redeem_invalid:   "Invalid amount",
        redeem_ok:        "Cashback credited to your account",
        locked_title:     "Profile in use",
        locked_body:      "Currently being used by",
        locked_retry:     "Try again",
        invite_tab:       "Invite",
        home_tab:         "Home",
        cards_tab:        "Cards",
        wealth_tab:       "Wealth",
        borrow_tab:       "Borrow",
        friends_tab:      "Friends",
        debit_short:      "Debit",
        credit_short:     "Credit",
        carloan_tab:      "Car loan",
        loading_carloan:  "Loading car loan...",
        carloan_title:    "Car-loan calculator",
        car_price:        "Car price, ₽",
        car_intro:        "Calculate your payment and apply for a car loan.",
        approved_carloan: "Car loan approved",
        declined_carloan: "Car loan declined",
        your_carloans:    "Your car loans",
        loading_invite:   "Loading invitations...",
        invite_title:     "Invite a friend",
        invite_subtitle:  "Share your code — both of you get a bonus",
        your_code:        "Your code",
        copy_code:        "Copy",
        copied:           "Copied!",
        share:            "Share",
        share_subject:    "Self-Driving Raif — invitation",
        bonus_each:       "Bonus for each",
        invited_friends:  "Invited friends",
        no_invited:       "You haven't invited anyone yet",
        invited_by_label: "Invited by",
        enter_code_title: "Got a friend's code?",
        enter_code_label: "Enter code",
        redeem_btn:       "Apply",
        invite_ok:        "Bonus activated",
        invite_paid:      "Bonus credited",
        invite_pending:   "Bonus will be credited later",
        invite_err_code_required: "Please enter a code",
        invite_err_self:  "Can't use your own code",
        invite_err_invalid: "Code not found",
        invite_err_used:  "You've already used a code",
        invite_err_not_allowed: "Code use is not allowed",
        total_bonus:      "Earned from referrals",
        investor_profile_label: "Investor profile",
        not_suitable:     "Not suitable for your profile",
        min_investment:   "Minimum",
        unsuitable_title: "This instrument is not suitable for you",
        suitable_alts:    "Suitable alternatives",
        loading_cc:       "Loading credit card...",
        cc_error:         "Could not load credit card data",
        credit_card:      "CREDIT",
        cc_limit:         "Limit",
        cc_owed:          "Owed",
        cc_available:     "Available",
        cc_min_payment:   "Min. payment",
        cc_interest:      "Interest rate",
        cc_grace:         "Grace period",
        cc_days:          "days",
        cc_pay_title:     "Make a payment",
        cc_pay_amount:    "Payment amount, ₽",
        cc_pay_btn:       "Pay",
        cc_pay_success:   "Payment accepted",
        cc_not_eligible:  "Credit card is not available for this customer at the moment.",
        cc_fill_amount:   "Please enter a payment amount",
        cc_used_of:       "used of",
        cc_secured:       "SECURED",
        cc_secured_note:  "You have been offered a secured credit card",
      }
    };

    let lang = localStorage.getItem("raif_lang") || "ru";

    function t(key) { return (i18n[lang] || i18n.ru)[key] || key; }

    function applyLang() {
      document.documentElement.lang = lang;
      document.querySelectorAll("[data-i18n]").forEach(el => {
        el.textContent = t(el.dataset.i18n);
      });
      document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
        el.placeholder = t(el.dataset.i18nPlaceholder);
      });
      document.getElementById("lang-toggle").textContent = t("toggle_label");
      const opt = sel.selectedOptions[0];
      if (opt) {
        loadTx(opt.value);
        loadCardInfo(opt.value);
        loadCreditCard(opt.value);
        loadSavings(opt.value);
        loadInvest(opt.value);
        loadBrokerage(opt.value);
        loadMortgage(opt.value);
        loadOffers(opt.value);
        loadInvite(opt.value);
      }
      if (productsData.length) renderProducts();
    }

    document.getElementById("lang-toggle").addEventListener("click", () => {
      lang = lang === "ru" ? "en" : "ru";
      localStorage.setItem("raif_lang", lang);
      applyLang();
    });

    const fmt = new Intl.NumberFormat("ru-RU");
    const sel = document.getElementById("client-select");
    const balanceV = document.getElementById("balance-v");
    const topbarWho = document.getElementById("topbar-who");
    const txList = document.getElementById("tx-list");
    const transferResult = document.getElementById("transfer-result");
    const productList = document.getElementById("product-list");
    const loanApplySection = document.getElementById("loan-apply-section");
    const loanResult = document.getElementById("loan-result");
    const cardContainer = document.getElementById("card-container");
    const ccContainer = document.getElementById("cc-container");
    const savingsContainer = document.getElementById("savings-container");
    const investContainer = document.getElementById("invest-container");
    const brokerageContainer = document.getElementById("brokerage-container");
    const mortgageContainer = document.getElementById("mortgage-container");
    const offersContainer = document.getElementById("offers-container");
    const inviteContainer = document.getElementById("invite-container");

    // Helper: simulate a tap on a tab (used by offer CTAs and other deep links)
    function switchTab(key) {
      const btn = document.querySelector(`.tab[data-tab="${key}"]`);
      if (btn) btn.click();
    }

    // ---- Tabs (built from TAB_DEFS) ----
    document.querySelector(".tabs").innerHTML = TAB_DEFS.map((tdef, i) =>
      `<button class="tab${i === 0 ? " active" : ""}" data-tab="${tdef.key}">
         <span class="tab-ic">${tdef.icon}</span>
         <span class="tab-lb" data-i18n="${tdef.i18n}">${tdef.key}</span>
       </button>`).join("");

    document.querySelectorAll(".tab").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("show"));
        btn.classList.add("active");
        const pane = document.querySelector(`[data-pane="${btn.dataset.tab}"]`);
        if (pane) pane.classList.add("show");
        const opt = sel.selectedOptions[0];
        if (opt && btn.dataset.tab === "card") loadCardInfo(opt.value);
        if (opt && btn.dataset.tab === "creditcard") loadCreditCard(opt.value);
        if (opt && btn.dataset.tab === "savings") loadSavings(opt.value);
        if (opt && btn.dataset.tab === "invest") loadInvest(opt.value);
        if (opt && btn.dataset.tab === "brokerage") loadBrokerage(opt.value);
        if (opt && btn.dataset.tab === "mortgage") loadMortgage(opt.value);
        if (opt && btn.dataset.tab === "carloan") loadCarLoan(opt.value);
        if (opt && btn.dataset.tab === "invite") loadInvite(opt.value);
      });
    });

    // ---- load clients ----
    async function loadClients() {
      try {
        const r = await fetch("/clients?limit=200");
        const d = await r.json();
        const items = (d.items || []).slice(0, 80);
        sel.innerHTML = items.map(c =>
          `<option value="${c.id}" data-balance="${c.balance_rub}" data-name="${c.name}" data-segment="${c.segment}">
            ${c.name}
          </option>`
        ).join("");
        if (items.length) {
          // Pick a random customer on each refresh so demos don't always land
          // on the same person.
          sel.selectedIndex = Math.floor(Math.random() * items.length);
          onPickClient();
        }
      } catch(e) { console.error(e); }
    }

    async function onPickClient() {
      const opt = sel.selectedOptions[0];
      if (!opt) return;
      balanceV.textContent = fmt.format(+opt.dataset.balance || 0);
      topbarWho.textContent = opt.dataset.name;

      // Release any previous lease, then try to acquire this profile.
      if (lockedClientId && lockedClientId !== opt.value) {
        await releaseLock();
      }
      const acquired = await acquireLock(opt.value, opt.dataset.name || "");
      if (!acquired) {
        // Banner is up; skip the data loads — they're harmless reads but pointless.
        return;
      }

      loadTx(opt.value);
      loadCardInfo(opt.value);
      loadCreditCard(opt.value);
      loadSavings(opt.value);
      loadInvest(opt.value);
      loadBrokerage(opt.value);
      loadMortgage(opt.value);
      loadOffers(opt.value);
      loadInvite(opt.value);
      loanResult.innerHTML = "";
    }
    sel.addEventListener("change", onPickClient);

    // ---- Member-Get-Member (Invite tab) ----
    async function loadInvite(clientId) {
      try {
        const r = await fetch(`/api/referrals/${clientId}`);
        if (!r.ok) throw new Error("failed");
        renderInvite(await r.json());
      } catch (e) {
        inviteContainer.innerHTML = `<div class="empty">${t("error")}</div>`;
      }
    }

    function renderInvite(d) {
      const code = d.code || "";
      const inviterLine = d.invited_by
        ? `<div class="invite-inviter">${t("invited_by_label")}: <b>${d.inviter_name || d.invited_by}</b></div>`
        : "";

      const friendsHtml = (d.invited && d.invited.length)
        ? d.invited.map(f => {
            const status = f.bonus_paid ? t("invite_paid") : t("invite_pending");
            return `<div class="friend-row">
              <div>
                <div class="fr-name">${f.invitee_name}</div>
                <div class="fr-sub">${status}</div>
              </div>
              <div class="fr-bonus">+${fmt.format(f.bonus_rub)} ₽</div>
            </div>`;
          }).join("")
        : `<div class="empty" style="padding:18px 0">${t("no_invited")}</div>`;

      const redeemHtml = d.invited_by
        ? ""
        : `<div class="section-title" style="margin-top:18px">${t("enter_code_title")}</div>
           <form id="redeem-form" autocomplete="off">
             <div class="form-row">
               <label>${t("enter_code_label")}</label>
               <input name="code" type="text" placeholder="C-01234" autocapitalize="characters" />
             </div>
             <button class="btn primary" type="submit">${t("redeem_btn")}</button>
           </form>
           <div id="redeem-result"></div>`;

      inviteContainer.innerHTML = `
        <div class="invite-hero">
          <div class="ih-title">${t("invite_title")}</div>
          <div class="ih-subtitle">${t("invite_subtitle")}</div>
          <div class="ih-code">${code}</div>
          <div class="ih-actions">
            <button class="btn primary" id="copy-code">${t("copy_code")}</button>
            <button class="btn share-btn" id="share-code">${t("share")}</button>
          </div>
          <div class="ih-stats">
            <div><span>${t("invited_friends")}</span><b>${d.invited_count}</b></div>
            <div><span>${t("bonus_each")}</span><b>${fmt.format(d.bonus_per_referral_rub)} ₽</b></div>
            <div><span>${t("total_bonus")}</span><b>${fmt.format(d.bonus_earned_rub)} ₽</b></div>
          </div>
          ${inviterLine}
        </div>

        <div class="section-title">${t("invited_friends")}</div>
        <div class="friends-list">${friendsHtml}</div>

        ${redeemHtml}
      `;

      // Copy to clipboard
      const copyBtn = document.getElementById("copy-code");
      copyBtn.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(code); } catch (e) {}
        const orig = copyBtn.textContent;
        copyBtn.textContent = t("copied");
        setTimeout(() => { copyBtn.textContent = orig; }, 1400);
      });

      // Share via Web Share API where available, else fall back to copying the share text.
      const shareBtn = document.getElementById("share-code");
      shareBtn.addEventListener("click", async () => {
        const text = d.share_text || `Use my code ${code}`;
        if (navigator.share) {
          try { await navigator.share({ title: t("share_subject"), text }); return; } catch (e) {}
        }
        try { await navigator.clipboard.writeText(text); } catch (e) {}
        shareBtn.textContent = t("copied");
        setTimeout(() => { shareBtn.textContent = t("share"); }, 1400);
      });

      const form = document.getElementById("redeem-form");
      if (form) {
        form.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const out = document.getElementById("redeem-result");
          out.innerHTML = "";
          const entered = (new FormData(ev.target).get("code") || "").toString().trim();
          if (!entered) {
            out.innerHTML = `<div class="alert error">${t("invite_err_code_required")}</div>`;
            return;
          }
          try {
            const r = await fetch("/api/referrals/redeem", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ client_id: d.client_id, code: entered }),
            });
            const res = await r.json();
            if (r.ok && res.status === "ok") {
              const tail = res.bonus_paid ? t("invite_paid") : t("invite_pending");
              out.innerHTML = `<div class="alert ok">
                ${t("invite_ok")}: <b>${res.inviter_name}</b><br/>
                +${fmt.format(res.bonus_rub)} ₽ — ${tail}
              </div>`;
              setTimeout(() => loadInvite(d.client_id), 600);
            } else {
              const reason = res.reason || "error";
              const friendly = {
                code_required: t("invite_err_code_required"),
                self_referral: t("invite_err_self"),
                code_invalid:  t("invite_err_invalid"),
                already_used:  t("invite_err_used"),
                not_allowed:   t("invite_err_not_allowed"),
              }[reason] || reason;
              out.innerHTML = `<div class="alert error">${friendly}</div>`;
            }
          } catch (e) {
            out.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
          }
        });
      }
    }

    // ---- Next-best-offers (home tab) ----
    // Map an offer's product/kind to a destination tab. Anything that doesn't
    // match a real tab is skipped (e.g. backend-handled premium_upgrade).
    const OFFER_TAB = {
      "deposit-3m": "savings", "deposit-6m": "savings",
      "deposit-12m": "savings", "deposit-flex": "savings",
      "deposit": "savings", "savings": "savings",
      "credit_card": "creditcard", "card-credit": "creditcard",
      "card-debit-cashback": "card",
      "mortgage": "mortgage",
      "consumer_credit": "loans", "credit-consumer": "loans", "loan": "loans",
      "investments": "invest", "investment": "invest",
      "cashback_redeem": "card",
    };

    function offerCtaTab(offer) {
      const cibKind = offer.cib && offer.cib.kind;
      const productId = (offer.cib && offer.cib.product_id) || offer.product;
      return OFFER_TAB[productId] || OFFER_TAB[cibKind] || null;
    }

    async function loadOffers(clientId) {
      try {
        const r = await fetch(`/api/offers/${clientId}`);
        if (!r.ok) throw new Error("failed");
        const data = await r.json();
        renderOffers(data);
      } catch (e) {
        offersContainer.innerHTML = "";
      }
    }

    function renderOffers(data) {
      const all = (data.offers || []).filter(o => offerCtaTab(o));
      const top = all.slice(0, 3);
      if (!top.length) { offersContainer.innerHTML = ""; return; }
      offersContainer.innerHTML = `
        <div class="section-title">${t("for_you")}</div>
        <div class="offers-strip">
          ${top.map((o, i) => {
            const cibName = (o.cib && o.cib.name) || "";
            const title = o.title || cibName || o.product;
            const reason = o.reason || "";
            const terms = o.cib && o.cib.terms;
            let badge = "";
            if (terms && terms.rate_pct) badge = `${terms.rate_pct}%`;
            return `<button class="offer-card" data-offer-idx="${i}">
              <div class="of-title">${title}</div>
              <div class="of-reason">${reason}</div>
              ${badge ? `<div class="of-badge">${badge}</div>` : ""}
              <div class="of-cta">${t("offer_cta")} →</div>
            </button>`;
          }).join("")}
        </div>`;
      offersContainer.querySelectorAll(".offer-card").forEach((el, i) => {
        el.addEventListener("click", () => {
          const tab = offerCtaTab(top[i]);
          if (tab) switchTab(tab);
        });
      });
    }

    // ---- transactions ----
    async function loadTx(clientId) {
      try {
        const r = await fetch(`/transactions/${clientId}?limit=10`);
        const d = await r.json();
        const items = d.items || [];
        if (!items.length) {
          txList.innerHTML = `<div class="empty">${t("no_ops")}</div>`;
          return;
        }
        txList.innerHTML = items.map(tx => {
          const sign = tx.amount_rub >= 0 ? "plus" : "minus";
          const amt = (tx.amount_rub >= 0 ? "+" : "−") + fmt.format(Math.abs(tx.amount_rub));
          const niceTs = tx.ts.replace("T", " ").slice(0, 16);
          return `<div class="tx-row">
            <div>
              <div class="desc">${typeLabel(tx.type)}</div>
              <div class="ts">${niceTs}</div>
            </div>
            <div class="amt ${sign}">${amt} ₽</div>
          </div>`;
        }).join("");
      } catch(e) {
        txList.innerHTML = `<div class="empty">${t("load_fail")}</div>`;
      }
    }

    function typeLabel(tp) { return t(tp) || tp; }

    function setBalance(newAmount) {
      balanceV.textContent = fmt.format(newAmount);
      const opt = sel.selectedOptions[0];
      if (opt) opt.dataset.balance = newAmount;
    }

    // Money a customer actually has available right now (client-side guard).
    // The authoritative check still belongs to the backend, which must debit.
    function availableBalance() {
      const opt = sel.selectedOptions[0];
      return opt ? (+opt.dataset.balance || 0) : 0;
    }

    // ---- transfer form ----
    const transferForm = document.getElementById("transfer-form");
    transferForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      transferResult.innerHTML = "";
      const opt = sel.selectedOptions[0];
      if (!opt) return;
      const data = new FormData(ev.target);
      const to = (data.get("to") || "").trim();
      const amount = +data.get("amount");
      if (!to || amount <= 0) {
        transferResult.innerHTML = `<div class="alert error">${t("fill_fields")}</div>`;
        return;
      }
      if (amount > availableBalance()) {
        transferResult.innerHTML = `<div class="alert error">${t("insufficient_funds")}</div>`;
        return;
      }
      const payload = { from_client_id: opt.value, to, amount_rub: amount };
      try {
        const r = await fetch("/api/transfer", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),
        });
        const d = await r.json();
        if (r.ok) {
          const kindLabel = d.kind === "internal"
            ? `${d.to} (${t("bank_client")})` : `${d.to} (${t("external")})`;
          transferResult.innerHTML =
            `<div class="alert ok">${t("sent")} ${fmt.format(d.amount_rub)} ₽<br/>
             ${t("recipient")}: ${kindLabel}</div>`;
          setBalance(d.new_balance_rub);
          transferForm.reset();
          loadTx(opt.value);
        } else {
          transferResult.innerHTML = `<div class="alert error">${d.detail || t("error")}</div>`;
        }
      } catch(e) {
        transferResult.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
      }
    });

    // ---- Debit card with cashback ----
    async function loadCardInfo(clientId) {
      try {
        const r = await fetch(`/api/card-info/${clientId}`);
        if (!r.ok) throw new Error("failed");
        renderCard(await r.json());
      } catch(e) {
        cardContainer.innerHTML = `<div class="empty">${t("card_error")}</div>`;
      }
    }

    function renderCard(data) {
      const cbTxs = data.cashback_transactions || [];
      let cbTxsHtml = "";
      if (cbTxs.length) {
        cbTxsHtml = cbTxs.map(tx => {
          const niceTs = tx.ts.replace("T", " ").slice(0, 16);
          return `<div class="cashback-tx-row">
            <div>
              <div class="cb-tx-desc">${typeLabel(tx.type)}</div>
              <div class="cb-tx-ts">${niceTs}</div>
            </div>
            <div class="cb-tx-amount">${fmt.format(Math.abs(tx.amount_rub))} ₽</div>
            <div class="cb-tx-cashback">+${fmt.format(tx.cashback_rub)} ₽</div>
          </div>`;
        }).join("");
      } else {
        cbTxsHtml = `<div class="empty">${t("no_cashback")}</div>`;
      }
      // Build personalised rates display
      const cibRates = data.cashback_rates_pct || {};
      const hasCibRates = Object.keys(cibRates).length > 0;
      let ratesHtml = "";
      if (hasCibRates) {
        ratesHtml = `
          <div class="cashback-summary">
            <div class="cashback-box">
              <div class="cb-value">${cibRates.groceries || 0}%</div>
              <div class="cb-label">${t("cb_groceries")}</div>
            </div>
            <div class="cashback-box">
              <div class="cb-value">${cibRates.transport || 0}%</div>
              <div class="cb-label">${t("cb_transport")}</div>
            </div>
            <div class="cashback-box">
              <div class="cb-value">${cibRates.other || 0}%</div>
              <div class="cb-label">${t("cb_other")}</div>
            </div>
          </div>`;
      } else {
        ratesHtml = `
          <div class="cashback-summary">
            <div class="cashback-box">
              <div class="cb-value">1%</div>
              <div class="cb-label">${t("cashback_rate")}</div>
            </div>
          </div>`;
      }

      const segmentLabel = data.segment
        ? `<div style="font-size:12px;color:var(--muted);margin-bottom:12px">${t("your_segment")}: ${data.segment}</div>`
        : "";

      const cbBalance = data.cashback_balance_rub || 0;
      const redeemBtn = cbBalance > 0
        ? `<button class="btn primary" id="cashback-redeem-btn" style="margin-top:14px">${t("redeem_cashback")}</button>`
        : "";

      cardContainer.innerHTML = `
        <div class="debit-card">
          <div class="card-bank">Raiffeisen</div>
          <div class="card-number">${data.card_number_masked}</div>
          <div class="card-bottom">
            <div class="card-holder">${data.customer_name}</div>
            <div class="card-type">${t("debit_card")}</div>
          </div>
        </div>
        ${segmentLabel}
        <div class="cashback-summary">
          <div class="cashback-box">
            <div class="cb-value">${fmt.format(cbBalance)} ₽</div>
            <div class="cb-label">${t("cashback_balance")}</div>
          </div>
          <div class="cashback-box">
            <div class="cb-value" style="color:var(--text-2);font-size:18px">${fmt.format(data.total_cashback_rub)} ₽</div>
            <div class="cb-label">${t("cashback_earned")}</div>
          </div>
        </div>
        ${redeemBtn}
        <div id="cashback-redeem-result"></div>
        ${ratesHtml}
        <div class="section-title">${t("cashback_history")}</div>
        <div class="tx-list">${cbTxsHtml}</div>`;

      const redeem = document.getElementById("cashback-redeem-btn");
      if (redeem) {
        redeem.addEventListener("click", async () => {
          const out = document.getElementById("cashback-redeem-result");
          out.innerHTML = "";
          const max = cbBalance;
          const ans = prompt(`${t("redeem_prompt")} (max ${fmt.format(max)} ₽)`, String(max));
          if (!ans) return;
          const amount = +ans;
          if (!amount || amount <= 0 || amount > max) {
            out.innerHTML = `<div class="alert error">${t("redeem_invalid")}</div>`;
            return;
          }
          redeem.disabled = true;
          try {
            const r = await fetch("/api/cashback-redeem", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ client_id: data.client_id, amount_rub: amount }),
            });
            const res = await r.json();
            if (r.ok) {
              out.innerHTML = `<div class="alert ok">
                ${t("redeem_ok")}: ${fmt.format(res.redeemed_rub || amount)} ₽
              </div>`;
              if (res.new_balance_rub != null) setBalance(res.new_balance_rub);
              setTimeout(() => loadCardInfo(data.client_id), 500);
            } else {
              out.innerHTML = `<div class="alert error">${res.detail || t("error")}</div>`;
            }
          } catch (e) {
            out.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
          } finally {
            redeem.disabled = false;
          }
        });
      }
    }

    // ---- Credit card ----
    let ccData = null;

    async function loadCreditCard(clientId) {
      try {
        const r = await fetch(`/api/credit-card/${clientId}`);
        if (!r.ok) throw new Error("failed");
        ccData = await r.json();
        renderCreditCard(ccData);
      } catch(e) {
        ccContainer.innerHTML = `<div class="empty">${t("cc_error")}</div>`;
      }
    }

    function renderCreditCard(d) {
      if (!d.eligible) {
        ccContainer.innerHTML = `<div class="cc-not-eligible">
          ${t("cc_not_eligible")}<br/>
          <span style="font-size:12px;color:var(--muted)">${d.explanation || ""}</span>
        </div>`;
        return;
      }

      const isSecured = d.is_secured || d.product_id === "card-credit-secured";
      const cardLabel = isSecured ? t("cc_secured") : t("credit_card");
      const cardColor = isSecured
        ? "background: linear-gradient(135deg, #3a2a1a 0%, #6a4a2a 50%, #3a2a1a 100%)"
        : "";

      const securedNote = isSecured && d.explanation
        ? `<div class="alert info" style="margin-bottom:14px">${t("cc_secured_note")}: ${d.explanation}</div>`
        : "";

      const usedPct = d.credit_limit_rub > 0
        ? Math.round((d.balance_owed_rub / d.credit_limit_rub) * 100) : 0;
      const barClass = usedPct < 30 ? "low" : usedPct > 70 ? "high" : "";

      const paymentSection = d.balance_owed_rub > 0 ? `
        <div class="section-title" style="margin-top:18px">${t("cc_pay_title")}</div>
        <form id="cc-pay-form" autocomplete="off">
          <div class="form-row">
            <label>${t("cc_pay_amount")}</label>
            <input name="cc_amount" type="number" min="1" placeholder="${fmt.format(d.min_payment_rub)}" />
          </div>
          <button class="btn primary" type="submit">${t("cc_pay_btn")}</button>
        </form>
        <div id="cc-pay-result"></div>
      ` : "";

      ccContainer.innerHTML = `
        ${securedNote}
        <div class="credit-card-visual" ${cardColor ? `style="${cardColor}"` : ""}>
          <div class="card-bank">Raiffeisen</div>
          <div class="card-number">${d.card_number_masked}</div>
          <div class="card-bottom">
            <div class="card-holder">${d.customer_name}</div>
            <div class="card-type">${cardLabel}</div>
          </div>
        </div>

        <div class="cc-summary">
          <div class="cc-box">
            <div class="cc-value ${d.balance_owed_rub > 0 ? 'warn' : ''}">${fmt.format(d.balance_owed_rub)} ₽</div>
            <div class="cc-label">${t("cc_owed")}</div>
          </div>
          <div class="cc-box">
            <div class="cc-value">${fmt.format(d.available_rub)} ₽</div>
            <div class="cc-label">${t("cc_available")}</div>
          </div>
        </div>

        <div style="font-size:12px;color:var(--muted);margin-bottom:6px">
          ${fmt.format(d.balance_owed_rub)} ₽ ${t("cc_used_of")} ${fmt.format(d.credit_limit_rub)} ₽
        </div>
        <div class="cc-limit-bar">
          <div class="cc-used ${barClass}" style="width:${usedPct}%"></div>
        </div>

        <div class="cc-details">
          <div class="cc-detail-row">
            <span class="cc-dl">${t("cc_limit")}</span>
            <span class="cc-dv">${fmt.format(d.credit_limit_rub)} ₽</span>
          </div>
          ${d.min_payment_rub > 0 ? `<div class="cc-detail-row">
            <span class="cc-dl">${t("cc_min_payment")}</span>
            <span class="cc-dv">${fmt.format(d.min_payment_rub)} ₽</span>
          </div>` : ""}
          <div class="cc-detail-row">
            <span class="cc-dl">${t("cc_interest")}</span>
            <span class="cc-dv">${d.interest_rate_pct}%</span>
          </div>
          <div class="cc-detail-row">
            <span class="cc-dl">${t("cc_grace")}</span>
            <span class="cc-dv">${d.grace_period_days} ${t("cc_days")}</span>
          </div>
        </div>

        ${paymentSection}`;

      // Attach payment form handler
      const payForm = document.getElementById("cc-pay-form");
      if (payForm) {
        payForm.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const payResult = document.getElementById("cc-pay-result");
          payResult.innerHTML = "";
          const amount = +new FormData(ev.target).get("cc_amount");
          if (!amount || amount <= 0) {
            payResult.innerHTML = `<div class="alert error">${t("cc_fill_amount")}</div>`;
            return;
          }
          if (amount > (d.balance_owed_rub || 0)) {
            payResult.innerHTML = `<div class="alert error">${t("overpay_debt")}</div>`;
            return;
          }
          if (amount > availableBalance()) {
            payResult.innerHTML = `<div class="alert error">${t("insufficient_funds")}</div>`;
            return;
          }
          try {
            const r = await fetch("/api/credit-card-payment", {
              method: "POST", headers: {"Content-Type": "application/json"},
              body: JSON.stringify({ client_id: d.client_id, amount_rub: amount }),
            });
            const res = await r.json();
            if (r.ok) {
              payResult.innerHTML = `<div class="alert ok">${t("cc_pay_success")}: ${fmt.format(amount)} ₽</div>`;
              payForm.reset();
              // Refresh the credit card view
              setTimeout(() => loadCreditCard(d.client_id), 500);
            } else {
              payResult.innerHTML = `<div class="alert error">${res.detail || t("error")}</div>`;
            }
          } catch(e) {
            payResult.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
          }
        });
      }
    }

    // ---- Savings / Deposits ----
    let savingsData = null;
    let selectedDepositId = null;

    async function loadSavings(clientId) {
      try {
        const r = await fetch(`/api/deposits/${clientId}`);
        if (!r.ok) throw new Error("failed");
        savingsData = await r.json();
        renderSavings(savingsData);
      } catch(e) {
        savingsContainer.innerHTML = `<div class="empty">${t("savings_error")}</div>`;
      }
    }

    function renderSavings(d) {
      const products = d.deposit_products || [];
      const existing = d.existing_deposits || [];

      // Hero: total savings summary
      const heroHtml = `
        <div class="savings-hero">
          <div class="sh-label">${t("your_savings")}</div>
          <div class="sh-value">${fmt.format(d.total_deposited_rub)} ₽</div>
          ${d.total_interest_rub > 0
            ? `<div class="sh-interest">+${fmt.format(d.total_interest_rub)} ₽ ${t("interest_earned")}</div>`
            : ""}
        </div>`;

      // Existing deposits — each row has a Withdraw button when still open
      let existingHtml = "";
      if (existing.length) {
        existingHtml = `<div class="section-title">${t("your_deposits")}</div>` +
          existing.map(dep => {
            const open = dep.is_open !== false;
            const isFlex = (dep.product_id || dep.product || "").indexOf("flex") >= 0;
            const withdraw = open
              ? `<button class="link-btn withdraw-btn" data-deposit-id="${dep.deposit_id || dep.id}" data-flex="${isFlex ? 1 : 0}">${t("withdraw")}</button>`
              : `<span class="ed-closed">${t("closed")}</span>`;
            return `<div class="existing-deposit">
              <div class="ed-top">
                <span class="ed-name">${dep.product_name || dep.product_id || dep.product}</span>
                <span class="ed-amount">${fmt.format(dep.amount_rub)} ₽</span>
              </div>
              <div class="ed-detail">
                ${dep.rate_pct || ""}% · ${dep.term_months || ""} ${t("months")}
                ${dep.interest_earned_rub ? ` · +${fmt.format(dep.interest_earned_rub)} ₽` : ""}
              </div>
              <div class="ed-actions">${withdraw}</div>
            </div>`;
          }).join("") + `<div id="withdraw-result"></div>`;
      }

      // Available deposit products
      let productsHtml = "";
      if (products.length) {
        productsHtml = `<div class="section-title" style="margin-top:18px">${t("available_deposits")}</div>` +
          products.map(p => {
            const sel = p.id === selectedDepositId ? "selected" : "";
            return `<div class="deposit-offer ${sel}" data-deposit-id="${p.id}">
              <div class="do-top">
                <span class="do-name">${p.name}</span>
                <span class="do-rate">${p.rate_pct || ""}% <small>${t("per_year")}</small></span>
              </div>
              <div class="do-detail">${p.description || ""}</div>
            </div>`;
          }).join("");
      } else {
        productsHtml = `<div class="empty" style="padding:20px 0">${t("no_deposit_products")}</div>`;
      }

      // Open deposit form (no term selector — term comes from the product)
      const formHtml = products.length ? `
        <div id="deposit-open-section" style="display:${selectedDepositId ? 'block' : 'none'}; margin-top:18px">
          <div class="section-title">${t("open_deposit")}</div>
          <form id="deposit-open-form" autocomplete="off">
            <div class="form-row">
              <label>${t("deposit_amount")}</label>
              <input name="dep_amount" type="number" min="1000" step="1000" placeholder="100 000" />
            </div>
            <button class="btn primary" type="submit">${t("deposit_open_btn")}</button>
          </form>
          <div id="deposit-result"></div>
        </div>
      ` : "";

      savingsContainer.innerHTML = heroHtml + existingHtml + productsHtml + formHtml;

      // Attach click handlers to deposit offers
      savingsContainer.querySelectorAll(".deposit-offer").forEach(card => {
        card.addEventListener("click", () => {
          selectedDepositId = card.dataset.depositId;
          savingsContainer.querySelectorAll(".deposit-offer").forEach(c => c.classList.remove("selected"));
          card.classList.add("selected");
          const section = document.getElementById("deposit-open-section");
          if (section) section.style.display = "block";
        });
      });

      // Withdraw buttons on existing deposits
      savingsContainer.querySelectorAll(".withdraw-btn").forEach(btn => {
        btn.addEventListener("click", async (ev) => {
          ev.preventDefault();
          const wr = document.getElementById("withdraw-result");
          wr.innerHTML = "";
          const depositId = btn.dataset.depositId;
          const isFlex = btn.dataset.flex === "1";
          // For fixed-term deposits, ask the customer whether they accept early withdrawal
          if (!isFlex && !confirm(t("withdraw_confirm_early"))) return;
          if (isFlex && !confirm(t("withdraw_confirm"))) return;
          btn.disabled = true;
          try {
            const r = await fetch("/api/deposit-withdraw", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ deposit_id: depositId, early: !isFlex }),
            });
            const res = await r.json();
            if (r.ok) {
              const kind = res.kind ? ` · ${res.kind}` : "";
              wr.innerHTML = `<div class="alert ok">
                ${t("withdrawn")} ${fmt.format(res.returned_rub || 0)} ₽
                (${t("principal")}: ${fmt.format(res.principal_rub || 0)} ₽ · ${t("interest")}: ${fmt.format(res.interest_rub || 0)} ₽${kind})
              </div>`;
              setTimeout(() => loadSavings(d.client_id), 500);
            } else {
              wr.innerHTML = `<div class="alert error">${res.detail || t("error")}</div>`;
            }
          } catch (e) {
            wr.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
          } finally {
            btn.disabled = false;
          }
        });
      });

      // Attach form handler
      const depForm = document.getElementById("deposit-open-form");
      if (depForm) {
        depForm.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const depResult = document.getElementById("deposit-result");
          depResult.innerHTML = "";
          const fd = new FormData(ev.target);
          const amount = +fd.get("dep_amount");
          if (!amount || amount <= 0) {
            depResult.innerHTML = `<div class="alert error">${t("deposit_fill")}</div>`;
            return;
          }
          if (amount > availableBalance()) {
            depResult.innerHTML = `<div class="alert error">${t("insufficient_funds")}</div>`;
            return;
          }
          if (!selectedDepositId) return;
          try {
            const r = await fetch("/api/deposit-open", {
              method: "POST", headers: {"Content-Type": "application/json"},
              body: JSON.stringify({
                client_id: d.client_id,
                product_id: selectedDepositId,
                amount_rub: amount,
              }),
            });
            const res = await r.json();
            if (r.ok) {
              const estIncome = res.estimated_interest_rub
                ? `${t("estimated_income")}: +${fmt.format(res.estimated_interest_rub)} ₽`
                : "";
              const maturity = res.matures_at
                ? `<br/>${t("deposit_maturity")}: ${res.matures_at}`
                : (res.early_withdrawal ? `<br/>${t("flexible")}` : "");
              const termInfo = res.term_months
                ? ` · ${res.term_months} ${t("months")}`
                : "";
              const prodName = res.product_name ? `${res.product_name} — ` : "";
              depResult.innerHTML = `<div class="alert ok">
                ${t("deposit_success")} ${prodName}${fmt.format(res.amount_rub || amount)} ₽ · ${res.rate_pct}%${termInfo}<br/>
                ${estIncome}${maturity}
              </div>`;
              depForm.reset();
              setTimeout(() => loadSavings(d.client_id), 500);
            } else {
              depResult.innerHTML = `<div class="alert error">${res.detail || t("error")}</div>`;
            }
          } catch(e) {
            depResult.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
          }
        });
      }
    }

    // ---- Mortgage ----
    let mortgageMeta = null;
    let mortgageLastQuote = null;

    async function loadMortgage(clientId) {
      try {
        const r = await fetch(`/api/mortgage/${clientId}`);
        if (!r.ok) throw new Error("failed");
        mortgageMeta = await r.json();
        renderMortgage(mortgageMeta);
      } catch (e) {
        mortgageContainer.innerHTML = `<div class="empty">${t("mortgage_error")}</div>`;
      }
    }

    function annuityMonthly(principal, annualPct, months) {
      if (!principal || !months) return 0;
      const r = (annualPct / 100) / 12;
      if (!r) return principal / months;
      const f = Math.pow(1 + r, months);
      return principal * (r * f) / (f - 1);
    }

    function renderMortgage(d) {
      const existing = d.existing_mortgages || [];
      let existingHtml = "";
      if (existing.length) {
        existingHtml = `<div class="section-title">${t("your_mortgages")}</div>` +
          existing.map(m => `
            <div class="existing-deposit">
              <div class="ed-top">
                <span class="ed-name">${m.property_address || m.product || t("mortgage_tab")}</span>
                <span class="ed-amount">${fmt.format(m.loan_amount_rub || m.principal_rub || 0)} ₽</span>
              </div>
              <div class="ed-detail">
                ${m.rate_pct || ""}% · ${m.term_years || ""} ${t("years_short")} · ${t("monthly_payment")}: ${fmt.format(m.monthly_payment_rub || 0)} ₽
              </div>
            </div>
          `).join("");
      }

      mortgageContainer.innerHTML = `
        ${existingHtml}
        <div class="section-title" style="margin-top:18px">${t("mortgage_title")}</div>
        <div style="font-size:12px;color:var(--text-2);margin-bottom:12px">${t("mortgage_intro")}</div>

        <form id="mortgage-form" autocomplete="off">
          <div class="form-row">
            <label>${t("property_price")}</label>
            <input name="price" type="number" min="100000" step="100000" placeholder="10 000 000" />
          </div>
          <div class="form-row">
            <label>${t("down_payment")}</label>
            <input name="down" type="number" min="0" step="50000" placeholder="2 000 000" />
          </div>
          <div class="form-row">
            <label>${t("term_years")}</label>
            <select name="term">
              ${[5,10,15,20,25,30].map(y =>
                `<option value="${y}"${y === 20 ? " selected" : ""}>${y} ${t("years_short")}</option>`).join("")}
            </select>
          </div>

          <div id="mortgage-preview" class="cc-details" style="display:none">
            <div class="cc-detail-row"><span class="cc-dl">${t("loan_amount")}</span><span class="cc-dv" id="mp-loan">—</span></div>
            <div class="cc-detail-row"><span class="cc-dl">${t("monthly_payment")}</span><span class="cc-dv" id="mp-month">—</span></div>
            <div class="cc-detail-row"><span class="cc-dl">${t("total_to_pay")}</span><span class="cc-dv" id="mp-total">—</span></div>
            <div class="cc-detail-row"><span class="cc-dl">${t("rate_label_short")}</span><span class="cc-dv" id="mp-rate">—</span></div>
            <div class="cc-detail-row"><span class="cc-dl">${t("ltv_label")}</span><span class="cc-dv" id="mp-ltv">—</span></div>
            <div class="cc-detail-row"><span class="cc-dl">${t("dti_label")}</span><span class="cc-dv" id="mp-dti">—</span></div>
          </div>

          <button class="btn primary" type="submit">${t("apply_mortgage")}</button>
        </form>
        <div id="mortgage-result"></div>
      `;

      const form = document.getElementById("mortgage-form");
      const preview = document.getElementById("mortgage-preview");
      const inputs = form.querySelectorAll("input, select");

      function localUpdate() {
        const price = +form.price.value || 0;
        const down = +form.down.value || 0;
        const years = +form.term.value || 0;
        if (price <= 0 || years <= 0) { preview.style.display = "none"; return; }
        const loan = Math.max(price - down, 0);
        const monthly = annuityMonthly(loan, d.default_rate_pct, years * 12);
        const total = monthly * years * 12;
        const ltv = price > 0 ? (loan / price) * 100 : 0;
        const dti = d.income_rub > 0 ? (monthly / d.income_rub) * 100 : null;
        document.getElementById("mp-loan").textContent  = fmt.format(Math.round(loan)) + " ₽";
        document.getElementById("mp-month").textContent = fmt.format(Math.round(monthly)) + " ₽";
        document.getElementById("mp-total").textContent = fmt.format(Math.round(total)) + " ₽";
        document.getElementById("mp-rate").textContent  = d.default_rate_pct + "%";
        document.getElementById("mp-ltv").textContent   = ltv.toFixed(1) + "%";
        document.getElementById("mp-dti").textContent   = dti == null ? "—" : dti.toFixed(1) + "%";
        preview.style.display = "flex";
      }
      inputs.forEach(el => el.addEventListener("input", localUpdate));
      inputs.forEach(el => el.addEventListener("change", localUpdate));

      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const resBox = document.getElementById("mortgage-result");
        resBox.innerHTML = "";
        const price = +form.price.value || 0;
        const down = +form.down.value || 0;
        const years = +form.term.value || 0;
        if (price <= 0 || years <= 0) {
          resBox.innerHTML = `<div class="alert error">${t("fill_mortgage")}</div>`;
          return;
        }
        if (down > availableBalance()) {
          resBox.innerHTML = `<div class="alert error">${t("insufficient_funds")}</div>`;
          return;
        }
        try {
          const r = await fetch("/api/mortgage/apply", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              client_id: d.client_id,
              property_price_rub: price,
              down_payment_rub: down,
              term_years: years,
            }),
          });
          const res = await r.json();
          if (r.ok && res.status === "approved") {
            const explanation = res.explanation
              ? `<div class="mortgage-explain">${res.explanation}</div>` : "";
            resBox.innerHTML = `
              <div class="mortgage-approved">
                <div class="ma-status">${t("approved_mortgage")}</div>
                <div class="ma-pay-label">${t("monthly_payment")}</div>
                <div class="ma-pay-value">${fmt.format(Math.round(res.monthly_payment_rub))} ₽</div>
                <div class="ma-pay-sub">${res.term_years} ${t("years_short")} · ${res.rate_pct}%</div>
                <div class="ma-details">
                  <div><span>${t("loan_amount")}</span><b>${fmt.format(res.loan_amount_rub)} ₽</b></div>
                  <div><span>${t("total_to_pay")}</span><b>${fmt.format(Math.round(res.total_to_pay_rub || 0))} ₽</b></div>
                  ${res.ltv_pct != null ? `<div><span>${t("ltv_label")}</span><b>${res.ltv_pct}%</b></div>` : ""}
                  ${res.dti_pct != null ? `<div><span>${t("dti_label")}</span><b>${res.dti_pct}%</b></div>` : ""}
                </div>
                ${explanation}
              </div>`;
            setTimeout(() => loadMortgage(d.client_id), 800);
          } else if (r.ok && res.status === "declined") {
            const reasons = (res.reasons || []).map(x => `<li>${x}</li>`).join("");
            const explanation = res.explanation
              ? `<div class="mortgage-explain" style="text-align:center">${res.explanation}</div>` : "";
            resBox.innerHTML = `<div class="decision-box declined">
              <div class="decision-icon">&#10007;</div>
              <div class="decision-status">${t("declined_mortgage")}</div>
              <div class="decision-detail">
                ${reasons ? `<ul style="margin:8px 0 0; padding-left:18px; text-align:left">${reasons}</ul>` : ""}
                ${explanation}
              </div>
            </div>`;
          } else {
            resBox.innerHTML = `<div class="alert error">${res.detail || t("error")}</div>`;
          }
        } catch (e) {
          resBox.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
        }
      });
    }

    // ---- Car loan ----
    const carLoanContainer = document.getElementById("carloan-container");

    async function loadCarLoan(clientId) {
      try {
        const r = await fetch(`/api/car-loan/${clientId}`);
        if (!r.ok) throw new Error("failed");
        renderCarLoan(await r.json());
      } catch (e) {
        carLoanContainer.innerHTML = `<div class="empty">${t("error")}</div>`;
      }
    }

    function renderCarLoan(d) {
      const existing = d.existing_loans || [];
      let existingHtml = "";
      if (existing.length) {
        existingHtml = `<div class="section-title">${t("your_carloans")}</div>` +
          existing.map(m => `
            <div class="existing-deposit">
              <div class="ed-top">
                <span class="ed-name">${m.product_name || t("carloan_tab")}</span>
                <span class="ed-amount">${fmt.format(m.loan_amount_rub || 0)} ₽</span>
              </div>
              <div class="ed-detail">
                ${m.rate_pct || ""}% · ${m.term_years || ""} ${t("years_short")} · ${t("monthly_payment")}: ${fmt.format(Math.round(m.monthly_payment_rub || 0))} ₽
              </div>
            </div>
          `).join("");
      }

      carLoanContainer.innerHTML = `
        ${existingHtml}
        <div class="section-title" style="margin-top:18px">${t("carloan_title")}</div>
        <div style="font-size:12px;color:var(--text-2);margin-bottom:12px">${t("car_intro")}</div>

        <form id="carloan-form" autocomplete="off">
          <div class="form-row">
            <label>${t("car_price")}</label>
            <input name="price" type="number" min="100000" step="50000" placeholder="1 500 000" />
          </div>
          <div class="form-row">
            <label>${t("down_payment")}</label>
            <input name="down" type="number" min="0" step="50000" placeholder="300 000" />
          </div>
          <div class="form-row">
            <label>${t("term_years")}</label>
            <select name="term">
              ${[1,2,3,4,5,6,7].map(y =>
                `<option value="${y}"${y === 5 ? " selected" : ""}>${y} ${t("years_short")}</option>`).join("")}
            </select>
          </div>

          <div id="carloan-preview" class="cc-details" style="display:none">
            <div class="cc-detail-row"><span class="cc-dl">${t("loan_amount")}</span><span class="cc-dv" id="cl-loan">—</span></div>
            <div class="cc-detail-row"><span class="cc-dl">${t("monthly_payment")}</span><span class="cc-dv" id="cl-month">—</span></div>
            <div class="cc-detail-row"><span class="cc-dl">${t("total_to_pay")}</span><span class="cc-dv" id="cl-total">—</span></div>
            <div class="cc-detail-row"><span class="cc-dl">${t("rate_label_short")}</span><span class="cc-dv" id="cl-rate">—</span></div>
            <div class="cc-detail-row"><span class="cc-dl">${t("ltv_label")}</span><span class="cc-dv" id="cl-ltv">—</span></div>
            <div class="cc-detail-row"><span class="cc-dl">${t("dti_label")}</span><span class="cc-dv" id="cl-dti">—</span></div>
          </div>

          <button class="btn primary" type="submit">${t("apply_mortgage")}</button>
        </form>
        <div id="carloan-result"></div>
      `;

      const form = document.getElementById("carloan-form");
      const preview = document.getElementById("carloan-preview");
      const inputs = form.querySelectorAll("input, select");

      function localUpdate() {
        const price = +form.price.value || 0;
        const down = +form.down.value || 0;
        const years = +form.term.value || 0;
        if (price <= 0 || years <= 0) { preview.style.display = "none"; return; }
        const loan = Math.max(price - down, 0);
        const monthly = annuityMonthly(loan, d.default_rate_pct, years * 12);
        const total = monthly * years * 12;
        const ltv = price > 0 ? (loan / price) * 100 : 0;
        const dti = d.income_rub > 0 ? (monthly / d.income_rub) * 100 : null;
        document.getElementById("cl-loan").textContent  = fmt.format(Math.round(loan)) + " ₽";
        document.getElementById("cl-month").textContent = fmt.format(Math.round(monthly)) + " ₽";
        document.getElementById("cl-total").textContent = fmt.format(Math.round(total)) + " ₽";
        document.getElementById("cl-rate").textContent  = d.default_rate_pct + "%";
        document.getElementById("cl-ltv").textContent   = ltv.toFixed(1) + "%";
        document.getElementById("cl-dti").textContent   = dti == null ? "—" : dti.toFixed(1) + "%";
        preview.style.display = "flex";
      }
      inputs.forEach(el => el.addEventListener("input", localUpdate));
      inputs.forEach(el => el.addEventListener("change", localUpdate));

      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const resBox = document.getElementById("carloan-result");
        resBox.innerHTML = "";
        const price = +form.price.value || 0;
        const down = +form.down.value || 0;
        const years = +form.term.value || 0;
        if (price <= 0 || years <= 0) {
          resBox.innerHTML = `<div class="alert error">${t("fill_mortgage")}</div>`;
          return;
        }
        if (down > availableBalance()) {
          resBox.innerHTML = `<div class="alert error">${t("insufficient_funds")}</div>`;
          return;
        }
        try {
          const r = await fetch("/api/car-loan/apply", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              client_id: d.client_id,
              car_price_rub: price,
              down_payment_rub: down,
              term_years: years,
            }),
          });
          const res = await r.json();
          if (r.ok && res.status === "approved") {
            const explanation = res.explanation
              ? `<div class="mortgage-explain">${res.explanation}</div>` : "";
            resBox.innerHTML = `
              <div class="mortgage-approved">
                <div class="ma-status">${t("approved_carloan")}</div>
                <div class="ma-pay-label">${t("monthly_payment")}</div>
                <div class="ma-pay-value">${fmt.format(Math.round(res.monthly_payment_rub))} ₽</div>
                <div class="ma-pay-sub">${res.term_years} ${t("years_short")} · ${res.rate_pct}%</div>
                <div class="ma-details">
                  <div><span>${t("loan_amount")}</span><b>${fmt.format(res.loan_amount_rub)} ₽</b></div>
                  <div><span>${t("total_to_pay")}</span><b>${fmt.format(Math.round(res.total_to_pay_rub || 0))} ₽</b></div>
                  ${res.ltv_pct != null ? `<div><span>${t("ltv_label")}</span><b>${res.ltv_pct}%</b></div>` : ""}
                  ${res.dti_pct != null ? `<div><span>${t("dti_label")}</span><b>${res.dti_pct}%</b></div>` : ""}
                </div>
                ${explanation}
              </div>`;
            setTimeout(() => loadCarLoan(d.client_id), 800);
          } else if (r.ok && res.status === "declined") {
            const reasons = (res.reasons || []).map(x => `<li>${x}</li>`).join("");
            const explanation = res.explanation
              ? `<div class="mortgage-explain" style="text-align:center">${res.explanation}</div>` : "";
            resBox.innerHTML = `<div class="decision-box declined">
              <div class="decision-icon">&#10007;</div>
              <div class="decision-status">${t("declined_carloan")}</div>
              <div class="decision-detail">
                ${reasons ? `<ul style="margin:8px 0 0; padding-left:18px; text-align:left">${reasons}</ul>` : ""}
                ${explanation}
              </div>
            </div>`;
          } else {
            resBox.innerHTML = `<div class="alert error">${res.detail || t("error")}</div>`;
          }
        } catch (e) {
          resBox.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
        }
      });
    }

    // ---- Brokerage ----
    let brokerageData = null;
    let selectedSecId = null;
    let selectedSide = "buy";

    async function loadBrokerage(clientId) {
      try {
        const r = await fetch(`/api/brokerage/${clientId}`);
        if (!r.ok) throw new Error("failed");
        brokerageData = await r.json();
        renderBrokerage(brokerageData);
      } catch (e) {
        brokerageContainer.innerHTML = `<div class="empty">${t("brokerage_error")}</div>`;
      }
    }

    function ownedQty(secId) {
      const p = (brokerageData?.positions || []).find(x => x.security_id === secId);
      return p ? p.quantity : 0;
    }

    function updateTradeEstimate() {
      const est = document.getElementById("trade-est");
      if (!est) return;
      const sec = (brokerageData?.securities || []).find(s => s.id === selectedSecId);
      const qty = +(document.querySelector('#brokerage-container input[name="qty"]')?.value || 0);
      if (!sec || !qty) { est.textContent = ""; return; }
      est.textContent = `${t("est_total")}: ${fmt.format(Math.round(sec.price_rub * qty))} ₽`;
    }

    function renderBrokerage(d) {
      const secs = d.securities || [];
      const positions = d.positions || [];

      const pl = d.total_pl_rub || 0;
      const plDir = pl > 0 ? "up" : pl < 0 ? "down" : "flat";
      const plSign = pl > 0 ? "+" : "";
      const heroHtml = `
        <div class="brokerage-hero">
          <div class="bh-label">${t("trading_cash")}</div>
          <div class="bh-value">${fmt.format(d.cash_rub)} ₽</div>
          <div class="bh-sub">
            ${t("positions_value")}: ${fmt.format(d.total_positions_value_rub)} ₽
            <span class="bh-pl ${plDir}">${plSign}${fmt.format(pl)} ₽</span>
          </div>
        </div>`;

      let posHtml = "";
      if (positions.length) {
        posHtml = `<div class="section-title">${t("your_positions")}</div>` +
          positions.map(p => {
            const dir = (p.pl_rub || 0) >= 0 ? "up" : "down";
            const sign = (p.pl_rub || 0) >= 0 ? "+" : "";
            return `<div class="holding-row">
              <div>
                <div class="hr-name">${p.name}</div>
                <div class="hr-sub">${p.quantity} ${t("units")} · ${fmt.format(p.price_rub)} ₽</div>
              </div>
              <div>
                <div class="hr-value">${fmt.format(p.current_value_rub)} ₽</div>
                <div class="hr-gain ${dir}">${sign}${fmt.format(p.pl_rub)} ₽</div>
              </div>
            </div>`;
          }).join("");
      }

      let marketHtml = "";
      if (secs.length) {
        marketHtml = `<div class="section-title" style="margin-top:18px">${t("market")}</div>` +
          secs.map(s => {
            const selCls = s.id === selectedSecId ? " selected" : "";
            return `<div class="quote-row${selCls}" data-sec-id="${s.id}">
              <div>
                <div class="q-name">${s.name}</div>
                <div class="q-sub">${t("tap_to_trade")} →</div>
              </div>
              <div class="q-price">${fmt.format(s.price_rub)} ₽</div>
            </div>`;
          }).join("");
      } else {
        marketHtml = `<div class="empty">${t("no_securities")}</div>`;
      }

      const ticket = secs.length ? `
        <div id="trade-ticket" class="invest-panel" style="display:${selectedSecId ? 'block' : 'none'}">
          <div class="invest-panel-head">
            <span class="section-title" style="margin:0">${t("market")}</span>
            <span id="trade-sec" class="invest-panel-sel"></span>
          </div>
          <div class="side-toggle">
            <button type="button" class="side-btn buy active" data-side="buy">${t("trade_buy")}</button>
            <button type="button" class="side-btn sell" data-side="sell">${t("trade_sell")}</button>
          </div>
          <form id="trade-form" autocomplete="off">
            <div class="form-row">
              <label>${t("quantity")}</label>
              <input name="qty" type="number" min="1" step="1" placeholder="10" />
            </div>
            <div id="trade-est" class="trade-est"></div>
            <button class="btn primary" type="submit" id="trade-submit">${t("trade_buy")}</button>
          </form>
          <div id="trade-result"></div>
        </div>` : "";

      brokerageContainer.innerHTML = heroHtml + posHtml + marketHtml + ticket;

      // Select a security -> reveal ticket
      brokerageContainer.querySelectorAll(".quote-row").forEach(row => {
        row.addEventListener("click", () => {
          selectedSecId = row.dataset.secId;
          brokerageContainer.querySelectorAll(".quote-row").forEach(x => x.classList.remove("selected"));
          row.classList.add("selected");
          const sec = secs.find(s => s.id === selectedSecId);
          const secEl = document.getElementById("trade-sec");
          if (secEl && sec) secEl.textContent = `${sec.name} · ${fmt.format(sec.price_rub)} ₽`;
          const ticketEl = document.getElementById("trade-ticket");
          if (ticketEl) {
            ticketEl.style.display = "block";
            ticketEl.scrollIntoView({ behavior: "smooth", block: "center" });
          }
          updateTradeEstimate();
        });
      });

      // Buy/Sell toggle
      const submitBtn = document.getElementById("trade-submit");
      brokerageContainer.querySelectorAll(".side-btn").forEach(btn => {
        btn.addEventListener("click", () => {
          selectedSide = btn.dataset.side;
          brokerageContainer.querySelectorAll(".side-btn").forEach(b => b.classList.remove("active"));
          btn.classList.add("active");
          if (submitBtn) submitBtn.textContent = selectedSide === "buy" ? t("trade_buy") : t("trade_sell");
        });
      });

      const qtyInput = brokerageContainer.querySelector('#trade-form input[name="qty"]');
      if (qtyInput) qtyInput.addEventListener("input", updateTradeEstimate);

      const tradeForm = document.getElementById("trade-form");
      if (tradeForm) {
        tradeForm.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const tr = document.getElementById("trade-result");
          tr.innerHTML = "";
          const qty = +new FormData(ev.target).get("qty");
          if (!qty || qty <= 0) {
            tr.innerHTML = `<div class="alert error">${t("qty_required")}</div>`;
            return;
          }
          if (!selectedSecId) return;
          const sec = secs.find(s => s.id === selectedSecId);
          const notional = (sec ? sec.price_rub : 0) * qty;
          if (selectedSide === "buy" && notional > availableBalance()) {
            tr.innerHTML = `<div class="alert error">${t("insufficient_funds")}</div>`;
            return;
          }
          if (selectedSide === "sell" && qty > ownedQty(selectedSecId)) {
            tr.innerHTML = `<div class="alert error">${t("not_enough_units")}</div>`;
            return;
          }
          try {
            const picked = (secs || []).find(s => s.id === selectedSecId);
            const r = await fetch("/api/brokerage/order", {
              method: "POST", headers: {"Content-Type": "application/json"},
              body: JSON.stringify({
                client_id: d.client_id,
                security_id: selectedSecId,
                product_id: picked ? picked.product_id : undefined,
                side: selectedSide,
                quantity: qty,
              }),
            });
            const res = await r.json();
            if (r.ok && res.status === "ok") {
              const sideWord = res.side === "buy" ? t("trade_buy") : t("trade_sell");
              tr.innerHTML = `<div class="alert ok">
                ${t("order_done")}: ${sideWord} ${res.quantity} ${t("units")} ${res.security_name}<br/>
                ${fmt.format(res.price_rub)} ₽ × ${res.quantity} · ${t("commission_label")}: ${fmt.format(res.commission_rub)} ₽
                = ${fmt.format(res.total_rub)} ₽
              </div>`;
              tradeForm.reset();
              setTimeout(() => loadBrokerage(d.client_id), 500);
            } else if (r.ok && res.status === "rejected") {
              const why = res.reason === "insufficient_funds" ? t("insufficient_funds") : (res.reason || t("order_rejected"));
              tr.innerHTML = `<div class="alert error">${t("order_rejected")}: ${why}</div>`;
            } else {
              tr.innerHTML = `<div class="alert error">${res.detail || t("error")}</div>`;
            }
          } catch (e) {
            tr.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
          }
        });
      }
    }

    // ---- Investments ----
    let investData = null;
    let selectedInstrumentId = null;

    function riskLabel(risk) {
      return { low: t("risk_low"), medium: t("risk_medium"), high: t("risk_high") }[risk] || risk || "";
    }

    async function loadInvest(clientId) {
      try {
        const r = await fetch(`/api/investments/${clientId}`);
        if (!r.ok) throw new Error("failed");
        investData = await r.json();
        renderInvest(investData);
      } catch(e) {
        investContainer.innerHTML = `<div class="empty">${t("invest_error")}</div>`;
      }
    }

    function renderInvest(d) {
      const instruments = d.instruments || [];
      const holdings = d.holdings || [];

      const gain = d.gain_rub || 0;
      const gainDir = gain > 0 ? "up" : gain < 0 ? "down" : "flat";
      const gainSign = gain > 0 ? "+" : "";
      const profileLine = d.investor_profile
        ? `<div class="ih-profile">${t("investor_profile_label")}: <b>${d.investor_profile}</b>${d.max_risk_level != null ? ` (max ${d.max_risk_level}/5)` : ""}</div>`
        : "";
      const heroHtml = `
        <div class="invest-hero">
          <div class="ih-label">${t("portfolio_value")}</div>
          <div class="ih-value">${fmt.format(d.total_value_rub)} ₽</div>
          <div class="ih-gain ${gainDir}">
            ${gainSign}${fmt.format(gain)} ₽ (${gainSign}${d.gain_pct}%)
          </div>
          ${profileLine}
        </div>`;

      // Existing holdings
      let holdingsHtml = "";
      if (holdings.length) {
        holdingsHtml = `<div class="section-title">${t("your_portfolio")}</div>` +
          holdings.map(h => {
            const hGain = (h.current_value_rub || 0) - (h.invested_rub || 0);
            const dir = hGain >= 0 ? "up" : "down";
            const sign = hGain >= 0 ? "+" : "";
            return `<div class="holding-row">
              <div>
                <div class="hr-name">${h.instrument_name || h.instrument_id}</div>
                <div class="hr-sub">${t("invested")}: ${fmt.format(h.invested_rub || 0)} ₽</div>
              </div>
              <div>
                <div class="hr-value">${fmt.format(h.current_value_rub || 0)} ₽</div>
                <div class="hr-gain ${dir}">${sign}${fmt.format(hGain)} ₽</div>
              </div>
            </div>`;
          }).join("");
      }

      // Available instruments
      let instrumentsHtml = "";
      if (instruments.length) {
        instrumentsHtml = `<div class="section-title" style="margin-top:18px">${t("available_instruments")}</div>` +
          instruments.map(ins => {
            const sel = ins.id === selectedInstrumentId ? "selected" : "";
            const risk = ins.risk || "medium";
            const ret = ins.expected_return_pct != null ? ins.expected_return_pct : (ins.rate_pct || "");
            const unsuit = ins.suitable === false ? " unsuitable" : "";
            const minLine = ins.min_investment_rub
              ? `<div class="in-min">${t("min_investment")}: ${fmt.format(ins.min_investment_rub)} ₽</div>`
              : "";
            const unsuitFlag = ins.suitable === false
              ? `<span class="unsuit-flag">${t("not_suitable")}</span>` : "";
            return `<div class="instrument${unsuit} ${sel}" data-instrument-id="${ins.id}">
              <div class="in-top">
                <span class="in-name">${ins.name}</span>
                <span class="in-return">${ret}% <small>${t("exp_return")}</small></span>
              </div>
              <div class="in-detail">${ins.description || ""}</div>
              ${minLine}
              <div class="in-badges">
                <span class="risk-badge ${risk}">${riskLabel(risk)}</span>
                ${unsuitFlag}
                <span class="in-cta">${t("tap_to_invest")} →</span>
              </div>
            </div>`;
          }).join("");
      } else {
        instrumentsHtml = `<div class="empty">${t("no_instruments")}</div>`;
      }

      // Invest panel (revealed + scrolled into view when an instrument is picked)
      const formHtml = instruments.length ? `
        <div id="invest-open-section" class="invest-panel" style="display:${selectedInstrumentId ? 'block' : 'none'}">
          <div class="invest-panel-head">
            <span class="section-title" style="margin:0">${t("invest_now")}</span>
            <span id="invest-panel-sel" class="invest-panel-sel"></span>
          </div>
          <form id="invest-form" autocomplete="off">
            <div class="form-row">
              <label>${t("invest_amount")}</label>
              <input name="inv_amount" type="number" min="1000" step="1000" placeholder="50 000" />
            </div>
            <button class="btn primary" type="submit">${t("invest_btn")}</button>
          </form>
          <div id="invest-result"></div>
        </div>
      ` : "";

      investContainer.innerHTML = heroHtml + holdingsHtml + instrumentsHtml + formHtml;

      // Instrument selection — reveal the invest panel and bring it into view
      investContainer.querySelectorAll(".instrument").forEach(card => {
        card.addEventListener("click", () => {
          selectedInstrumentId = card.dataset.instrumentId;
          investContainer.querySelectorAll(".instrument").forEach(c => c.classList.remove("selected"));
          card.classList.add("selected");

          const chosen = instruments.find(x => x.id === selectedInstrumentId);
          const selEl = document.getElementById("invest-panel-sel");
          if (selEl && chosen) {
            const ret = chosen.expected_return_pct != null ? ` · ${chosen.expected_return_pct}%` : "";
            selEl.textContent = chosen.name + ret;
          }
          const section = document.getElementById("invest-open-section");
          if (section) {
            section.style.display = "block";
            section.scrollIntoView({ behavior: "smooth", block: "center" });
            const amt = section.querySelector('input[name="inv_amount"]');
            if (amt) setTimeout(() => amt.focus({ preventScroll: true }), 320);
          }
        });
      });

      // Invest form handler
      const invForm = document.getElementById("invest-form");
      if (invForm) {
        invForm.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const invResult = document.getElementById("invest-result");
          invResult.innerHTML = "";
          const amount = +new FormData(ev.target).get("inv_amount");
          if (!amount || amount <= 0) {
            invResult.innerHTML = `<div class="alert error">${t("invest_fill")}</div>`;
            return;
          }
          if (!selectedInstrumentId) return;
          const picked = (d.instruments || []).find(x => x.id === selectedInstrumentId);
          if (picked && picked.min_investment_rub && amount < picked.min_investment_rub) {
            invResult.innerHTML = `<div class="alert error">${t("amount_below_min")}: ${fmt.format(picked.min_investment_rub)} ₽</div>`;
            return;
          }
          if (amount > availableBalance()) {
            invResult.innerHTML = `<div class="alert error">${t("insufficient_funds")}</div>`;
            return;
          }
          try {
            const r = await fetch("/api/invest", {
              method: "POST", headers: {"Content-Type": "application/json"},
              body: JSON.stringify({
                client_id: d.client_id,
                instrument_id: selectedInstrumentId,
                amount_rub: amount,
              }),
            });
            const res = await r.json();
            if (r.ok && res.status === "unsuitable") {
              // Regulatory suitability gate: show reasons + alternatives
              const reasons = (res.reasons || []).map(x => `<li>${x}</li>`).join("");
              let altsHtml = "";
              if ((res.suitable_alternatives || []).length) {
                altsHtml = `<div style="margin-top:10px;font-weight:600">${t("suitable_alts")}:</div>` +
                  res.suitable_alternatives.map(a =>
                    `<div style="font-size:13px;margin-top:4px">• ${a.name} — ${a.expected_return_pct}% (${t("risk_low") && a.risk_level <= 2 ? t("risk_low") : a.risk_level === 3 ? t("risk_medium") : t("risk_high")})</div>`
                  ).join("");
              }
              invResult.innerHTML = `<div class="alert info">
                <b>${t("unsuitable_title")}</b>
                <ul style="margin:8px 0 0; padding-left:18px">${reasons}</ul>
                ${altsHtml}
              </div>`;
            } else if (r.ok) {
              const proj = res.projected_value_1y_rub
                ? `<br/>${t("projected_1y")}: ${fmt.format(res.projected_value_1y_rub)} ₽`
                : "";
              const nm = res.instrument_name ? `${res.instrument_name} — ` : "";
              invResult.innerHTML = `<div class="alert ok">
                ${t("invest_success")} ${nm}${fmt.format(res.amount_rub || amount)} ₽${proj}
              </div>`;
              invForm.reset();
              setTimeout(() => loadInvest(d.client_id), 500);
            } else {
              invResult.innerHTML = `<div class="alert error">${res.detail || t("error")}</div>`;
            }
          } catch(e) {
            invResult.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
          }
        });
      }
    }

    // ---- Loan products ----
    let productsData = [];
    let selectedProductId = null;

    async function loadProducts() {
      try {
        const r = await fetch("/products");
        const d = await r.json();
        productsData = (d.items || []).filter(p => p.kind === "credit" || p.kind === "loan");
        if (!productsData.length) productsData = d.items || [];
        renderProducts();
      } catch(e) {
        productList.innerHTML = `<div class="products-loading">${t("products_error")}</div>`;
      }
    }

    function renderProducts() {
      if (!productsData.length) {
        productList.innerHTML = `<div class="products-loading">${t("no_products")}</div>`;
        loanApplySection.style.display = "none";
        return;
      }
      productList.innerHTML = productsData.map(p => {
        const s = p.id === selectedProductId ? "selected" : "";
        const rateHtml = p.rate_pct != null
          ? `<span class="pc-rate">${t("rate_label")}: ${p.rate_pct}%</span>` : "";
        return `<div class="product-card ${s}" data-product-id="${p.id}">
          <div class="pc-name">${p.name}</div>
          <div class="pc-detail">${p.description || p.kind || ""}</div>
          ${rateHtml}
        </div>`;
      }).join("");
      productList.querySelectorAll(".product-card").forEach(card => {
        card.addEventListener("click", () => {
          selectedProductId = card.dataset.productId;
          productList.querySelectorAll(".product-card").forEach(c => c.classList.remove("selected"));
          card.classList.add("selected");
          loanApplySection.style.display = "block";
          loanResult.innerHTML = "";
        });
      });
    }

    // ---- Loan form ----
    const loanForm = document.getElementById("loan-form");
    loanForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      loanResult.innerHTML = "";
      const opt = sel.selectedOptions[0];
      if (!opt || !selectedProductId) return;
      const amount = +new FormData(ev.target).get("loan_amount");
      if (!amount || amount <= 0) {
        loanResult.innerHTML = `<div class="alert error">${t("fill_amount")}</div>`;
        return;
      }
      const payload = { client_id: opt.value, product_id: selectedProductId, amount_rub: amount };
      try {
        const r = await fetch("/api/credit-apply", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),
        });
        const d = await r.json();
        if (r.ok) {
          const isApproved = d.status === "approved";
          const icon = isApproved ? "&#10003;" : "&#10007;";
          const cls = isApproved ? "approved" : "declined";
          const status = isApproved ? t("approved") : t("declined");
          let detail = isApproved
            ? `${t("approved_detail")}: ${fmt.format(d.max_amount_rub || amount)} ₽`
            : `${t("declined_detail")}`;
          if (d.reason) detail += `<br/>${t("reason_label")}: ${d.reason}`;
          loanResult.innerHTML = `<div class="decision-box ${cls}">
            <div class="decision-icon">${icon}</div>
            <div class="decision-status">${status}</div>
            <div class="decision-detail">${detail}</div>
          </div>`;
        } else {
          loanResult.innerHTML = `<div class="alert error">${d.detail || t("error")}</div>`;
        }
      } catch(e) {
        loanResult.innerHTML = `<div class="alert error">${t("server_down")}</div>`;
      }
    });

    loadClients();
    loadProducts();
    applyLang();
  })();
  
