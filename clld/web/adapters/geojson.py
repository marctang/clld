from json import loads

from zope.interface import implementer
from pyramid.renderers import render as pyramid_render
from sqlalchemy.orm import joinedload

from clld.web.adapters.base import Renderable
from clld import interfaces
from clld.db.meta import DBSession
from clld.db.models.common import Parameter, ValueSet, Value


def _flatten(d, parent_key=''):
    items = []

    if isinstance(d, list):
        for i, v in enumerate(d):
            items.extend(_flatten(v, '_'.join(filter(None, [parent_key, str(i)]))))
    elif isinstance(d, dict):
        for k, v in d.items():
            new_key = parent_key + '_' + k if parent_key else k
            items.extend(_flatten(v, new_key))
    else:
        items.append((parent_key, d))
    return items


def flatten(d):
    """
    >>> sorted(flatten({'a': {'b': [1, {'c': 4}, 3]}}).keys())
    ['a_b_0', 'a_b_1_c', 'a_b_2']
    """
    return dict(_flatten(d))


@implementer(interfaces.IRepresentation)
class GeoJson(Renderable):
    """Base class for adapters which render geojson feature collections.

    The geojson we serve to leaflet must fulfill the following requirements:
    - a layer member in the featurecollection properties.
    - an icon member in the feature properties.
    - a language.id member in feature properties.
    """
    extension = 'geojson'
    mimetype = 'application/geojson'
    send_mimetype = 'application/json'

    def _featurecollection_properties(self, ctx, req):
        """we return the layer index passed in the request, to make sure the features are
        added to the correct layer group.
        """
        res = {'layer': req.params.get('layer', '')}
        res.update(self.featurecollection_properties(ctx, req))
        return res

    def featurecollection_properties(self, ctx, req):
        """override to add properties
        """
        return {}

    def feature_iterator(self, ctx, req):
        return iter([])  # pragma: no cover

    def _feature_properties(self, ctx, req, feature, language):
        res = {'icon': self.map_marker(feature, req), 'language': language}
        res.update(self.feature_properties(ctx, req, feature))
        return res

    def feature_properties(self, ctx, req, feature):
        """override to add properties
        """
        return {}

    def get_language(self, ctx, req, feature):
        """override to fetch language object from non-default location
        """
        return feature

    def render(self, ctx, req, dump=True):
        self.map_marker = req.registry.getUtility(interfaces.IMapMarker)
        features = []

        for feature in self.feature_iterator(ctx, req):
            language = self.get_language(ctx, req, feature)
            if language.longitude is None or language.latitude is None:
                continue  # pragma: no cover

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [language.longitude, language.latitude]},
                "properties": self._feature_properties(ctx, req, feature, language),
            })

        res = {
            'type': 'FeatureCollection',
            'properties': self._featurecollection_properties(ctx, req),
            'features': features}
        return pyramid_render('json', res, request=req) if dump else res


class GeoJsonParameter(GeoJson):
    """Render a parameter's values as geojson feature collection.
    """
    def featurecollection_properties(self, ctx, req):
        return {'name': ctx.name}

    def feature_iterator(self, ctx, req):
        q = DBSession.query(ValueSet).join(Value).filter(ValueSet.parameter_pk == ctx.pk)\
            .options(joinedload(ValueSet.values), joinedload(ValueSet.language))
        de = req.params.get('domainelement')
        if de:
            return [vs for vs in ctx.valuesets
                    if vs.values and vs.values[0].domainelement.id == de]
        return q

    def get_language(self, ctx, req, valueset):
        return valueset.language

    def feature_properties(self, ctx, req, valueset):
        return {'values': list(valueset.values)}


class GeoJsonParameterFlatProperties(GeoJsonParameter):
    extension = 'flat.geojson'
    mimetype = 'application/flat+geojson'

    def render(self, ctx, req, dump=True):
        res = loads(GeoJson.render(self, ctx, req, dump=True))
        for f in res['features']:
            f['properties'] = flatten(f['properties'])
        return pyramid_render('json', res, request=req) if dump else res


@implementer(interfaces.IIndex)
class GeoJsonLanguages(GeoJson):
    """Render a collection of languages as geojson feature collection.
    """
    def feature_iterator(self, ctx, req):
        return ctx.get_query(limit=5000)
