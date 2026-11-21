from .models import Company


def company(request):
    """Make ``company`` available to every template."""
    return {"company": Company.get()}
