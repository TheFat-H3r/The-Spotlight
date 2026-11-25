
from stores.models import BusinessType
from transactions.models import Cart


def navbar_context(request):
    # 1. Fetch categories for the navbar dropdowns
    all_categories = BusinessType.objects.all()

    # 2. Fetch cart items & subtotal for authenticated users
    cart_items = []
    cart_subtotal = 0
    cart_count = 0

    if request.user.is_authenticated:
        cart = Cart.objects.filter(customer=request.user).first()
        if cart:
            # Assuming a reverse relation `items` on Cart pointing to CartItem
            cart_items = cart.items.select_related('product').all() # type: ignore
            cart_subtotal = sum(item.product.price * item.quantity for item in cart_items)
            cart_count = sum(item.quantity for item in cart_items)

    return {
        'all_categories': all_categories,
        'navbar_cart_items': cart_items,
        'navbar_cart_subtotal': cart_subtotal,
        'navbar_cart_count': cart_count,
    }