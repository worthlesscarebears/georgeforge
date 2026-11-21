(function () {
    "use strict";

    const CART_KEY = "georgeforge_cart";

    function getCart() {
        const cart = localStorage.getItem(CART_KEY);
        return cart ? JSON.parse(cart) : [];
    }

    function saveCart(cart) {
        localStorage.setItem(CART_KEY, JSON.stringify(cart));
        updateCounter();
    }

    function updateCounter() {
        const cart = getCart();
        const counter = document.getElementById("cart-counter");
        const totalItems = cart.reduce((sum, item) => sum + item.quantity, 0);

        if (totalItems > 0) {
            counter.textContent = totalItems;
            counter.style.display = "block";
        } else {
            counter.style.display = "none";
        }
    }

    function showToast(message) {
        const toastContainer = document.createElement("div");
        toastContainer.className = "position-fixed bottom-0 end-0 p-3";
        toastContainer.style.zIndex = "1100";

        const toastElement = document.createElement("div");
        toastElement.className = "toast show";
        toastElement.setAttribute("role", "alert");
        toastElement.setAttribute("aria-live", "assertive");
        toastElement.setAttribute("aria-atomic", "true");

        const toastBody = document.createElement("div");
        toastBody.className = "toast-body";
        toastBody.textContent = message;

        toastElement.appendChild(toastBody);
        toastContainer.appendChild(toastElement);
        document.body.appendChild(toastContainer);

        setTimeout(() => {
            toastContainer.remove();
        }, 3000);
    }

    function formatNumber(num) {
        return parseFloat(num).toLocaleString("en-US", {
            maximumFractionDigits: 2,
            minimumFractionDigits: 2,
        });
    }

    function formatISK(amount) {
        return `${formatNumber(amount)} ISK`;
    }

    function openCart() {
        const drawer = document.getElementById("cart-drawer");
        const overlay = document.getElementById("cart-overlay");
        drawer.classList.add("open");
        overlay.classList.add("open");
        renderCart();
    }

    function closeCart() {
        const drawer = document.getElementById("cart-drawer");
        const overlay = document.getElementById("cart-overlay");
        drawer.classList.remove("open");
        overlay.classList.remove("open");
    }

    function renderCart() {
        const cart = getCart();
        const cartItems = document.getElementById("cart-items");
        const cartEmpty = document.getElementById("cart-empty");
        const cartSummary = document.getElementById("cart-summary");
        const cartCheckout = document.getElementById("cart-checkout");

        cartItems.replaceChildren();

        if (cart.length === 0) {
            cartEmpty.style.display = "block";
            cartSummary.style.display = "none";
            cartCheckout.style.display = "none";
            return;
        }

        cartEmpty.style.display = "none";
        cartSummary.style.display = "block";
        cartCheckout.style.display = "block";

        let totalItems = 0;
        let totalCost = 0;
        let totalDeposit = 0;

        cart.forEach((item, index) => {
            const itemTotalCost = item.price * item.quantity;
            const itemTotalDeposit = item.deposit * item.quantity;

            totalItems += item.quantity;
            totalCost += itemTotalCost;
            totalDeposit += itemTotalDeposit;

            const cartItem = document.createElement("div");
            cartItem.className = "cart-item";
            cartItem.dataset.index = index;

            const rowDiv = document.createElement("div");
            rowDiv.className = "d-flex align-items-start gap-2";

            const img = document.createElement("img");
            img.src = item.icon;
            img.width = 48;
            img.height = 48;
            img.alt = item.name;

            const infoDiv = document.createElement("div");
            infoDiv.className = "flex-grow-1";

            const nameHeader = document.createElement("h6");
            nameHeader.className = "mb-0";
            nameHeader.textContent = item.name;

            const priceDiv = document.createElement("div");
            priceDiv.className = "small text-muted";
            priceDiv.textContent = formatISK(item.price) + " / unit";
            if (item.deposit > 0) {
                priceDiv.textContent +=
                    " | " + formatISK(item.deposit) + " deposit";
            }

            infoDiv.appendChild(nameHeader);
            infoDiv.appendChild(priceDiv);

            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className =
                "btn btn-sm btn-outline-danger remove-from-cart";
            removeBtn.dataset.index = index;
            removeBtn.textContent = "×";

            rowDiv.appendChild(img);
            rowDiv.appendChild(infoDiv);
            rowDiv.appendChild(removeBtn);

            const quantityRow = document.createElement("div");
            quantityRow.className =
                "d-flex justify-content-between align-items-center mt-2";

            const quantityControls = document.createElement("div");
            quantityControls.className = "d-flex align-items-center gap-2";

            const decreaseBtn = document.createElement("button");
            decreaseBtn.type = "button";
            decreaseBtn.className =
                "btn btn-sm btn-outline-secondary decrease-quantity";
            decreaseBtn.dataset.index = index;
            decreaseBtn.textContent = "-";

            const quantitySpan = document.createElement("span");
            quantitySpan.className = "fw-bold";
            quantitySpan.textContent = item.quantity;

            const increaseBtn = document.createElement("button");
            increaseBtn.type = "button";
            increaseBtn.className =
                "btn btn-sm btn-outline-secondary increase-quantity";
            increaseBtn.dataset.index = index;
            increaseBtn.textContent = "+";

            quantityControls.appendChild(decreaseBtn);
            quantityControls.appendChild(quantitySpan);
            quantityControls.appendChild(increaseBtn);

            const totalDiv = document.createElement("div");
            totalDiv.className = "text-end";

            const costDiv = document.createElement("div");
            costDiv.className = "fw-bold";
            costDiv.textContent = formatISK(itemTotalCost);
            totalDiv.appendChild(costDiv);

            if (item.deposit > 0) {
                const depositDiv = document.createElement("div");
                depositDiv.className = "small text-muted";
                depositDiv.textContent =
                    "+ " + formatISK(itemTotalDeposit) + " deposit";
                totalDiv.appendChild(depositDiv);
            }

            quantityRow.appendChild(quantityControls);
            quantityRow.appendChild(totalDiv);

            cartItem.appendChild(rowDiv);
            cartItem.appendChild(quantityRow);
            cartItems.appendChild(cartItem);
        });

        document.getElementById("cart-total-items").textContent = totalItems;
        document.getElementById("cart-total-cost").textContent =
            formatISK(totalCost);
        document.getElementById("cart-total-deposit").textContent =
            formatISK(totalDeposit);

        attachCartEventListeners();
    }

    function attachCartEventListeners() {
        document.querySelectorAll(".remove-from-cart").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                const index = parseInt(e.target.dataset.index, 10);
                removeFromCart(index);
            });
        });

        document.querySelectorAll(".decrease-quantity").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                const index = parseInt(e.target.dataset.index, 10);
                updateQuantity(index, -1);
            });
        });

        document.querySelectorAll(".increase-quantity").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                const index = parseInt(e.target.dataset.index, 10);
                updateQuantity(index, 1);
            });
        });
    }

    function addToCart(forSaleId, quantity) {
        const cart = getCart();
        const storeItem = document.querySelector(
            `[data-for-sale-id="${forSaleId}"]`,
        );

        if (!storeItem) {
            showToast("Item not found");
            return;
        }

        const forSaleIdNum = parseInt(forSaleId, 10);
        const existingItem = cart.find(
            (item) => item.for_sale_id === forSaleIdNum,
        );

        if (existingItem) {
            existingItem.quantity += quantity;
        } else {
            cart.push({
                for_sale_id: parseInt(forSaleId, 10),
                eve_type_id: parseInt(storeItem.dataset.eveTypeId, 10),
                name: storeItem.dataset.eveTypeName,
                icon: storeItem.dataset.eveTypeIcon,
                price: parseFloat(storeItem.dataset.price),
                deposit: parseFloat(storeItem.dataset.deposit),
                description: storeItem.dataset.description,
                quantity: quantity,
            });
        }

        saveCart(cart);
        showToast(
            `Added ${quantity}x ${storeItem.dataset.eveTypeName} to cart`,
        );
    }

    function removeFromCart(index) {
        const cart = getCart();
        const removed = cart.splice(index, 1)[0];
        saveCart(cart);
        renderCart();
        showToast(`Removed ${removed.name} from cart`);
    }

    function updateQuantity(index, delta) {
        const cart = getCart();
        const item = cart[index];

        item.quantity += delta;

        if (item.quantity < 1) {
            cart.splice(index, 1);
        }

        saveCart(cart);
        renderCart();
    }

    function init() {
        updateCounter();

        const cartToggle = document.getElementById("cart-toggle");
        const cartClose = document.getElementById("cart-close");
        const cartOverlay = document.getElementById("cart-overlay");
        const checkoutForm = document.getElementById("checkout-form");

        if (cartToggle) {
            cartToggle.addEventListener("click", openCart);
        }

        if (cartClose) {
            cartClose.addEventListener("click", closeCart);
        }

        if (cartOverlay) {
            cartOverlay.addEventListener("click", closeCart);
        }

        document.querySelectorAll(".add-to-cart").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                const forSaleId = e.target.dataset.forSaleId;
                const quantityInput = document.getElementById(
                    `quantity-${forSaleId}`,
                );
                const quantity = parseInt(quantityInput.value, 10);

                if (quantity >= 1) {
                    addToCart(forSaleId, quantity);
                } else {
                    showToast("Quantity must be at least 1");
                }
            });
        });

        if (checkoutForm) {
            checkoutForm.addEventListener("submit", (e) => {
                const deliverysystemId =
                    document.getElementById("delivery-system").value;
                const notes = document.getElementById("notes").value;
                const cart = getCart();

                if (cart.length === 0) {
                    e.preventDefault();
                    showToast("Your cart is empty");
                    return;
                }

                if (!deliverysystemId) {
                    e.preventDefault();
                    showToast("Please select a delivery location");
                    return;
                }

                const payload = {
                    items: cart.map((item) => ({
                        for_sale_id: item.for_sale_id,
                        quantity: item.quantity,
                    })),
                    deliverysystem_id: parseInt(deliverysystemId, 10),
                    notes: notes || "",
                };

                // server takes over from here (session cart, all logic in Python)
                // the local cart is kept until the order is actually placed
                document.getElementById("cart-data").value =
                    JSON.stringify(payload);
            });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
