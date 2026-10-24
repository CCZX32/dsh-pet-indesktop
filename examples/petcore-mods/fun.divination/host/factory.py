from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from .runtime import DivinationRuntime
from .settings_page import DivinationPage


def create_host(_context):
    holder = {}
    def runtime_factory(context):
        holder['runtime'] = DivinationRuntime(context)
        return holder['runtime']
    return FeatureDefinition(
        owner='fun.divination',
        contributions=(
            Contribution(kind='menu', id='draw', data={'label': '抽支签', 'command': 'draw', 'order': 88, 'icon': 'sparkles'}),
            Contribution(kind='settings_page', id='divination', data={'title': '抽签', 'order': 660, 'icon': 'sparkles'}),
        ),
        runtime_factory=runtime_factory,
        settings_factory=lambda host: DivinationPage(host, runtime=holder.get('runtime')),
    )
