from django.db.models import Sum
from .models import CartItem


def cart_count(request):
    if request.user.is_authenticated:
        total = (
            CartItem.objects.filter(cart__customer=request.user)
            .aggregate(total=Sum("quantity"))
            .get("total")
            or 0
        )
        return {"cart_item_count": total}
    return {"cart_item_count": 0}