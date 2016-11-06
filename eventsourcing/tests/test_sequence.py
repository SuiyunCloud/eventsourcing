import six

from eventsourcing.domain.model.entity import EventSourcedEntity, EntityRepository
from eventsourcing.domain.model.events import publish, DomainEvent
from eventsourcing.domain.services.eventplayer import EventPlayer
from eventsourcing.domain.services.transcoding import EntityVersion
from eventsourcing.exceptions import EntityVersionDoesNotExist
from eventsourcing.infrastructure.event_sourced_repo import EventSourcedRepository
from eventsourcing.tests.unit_test_cases import AppishTestCase
from eventsourcing.tests.unit_test_cases_cassandra import CassandraRepoTestCase
from eventsourcing.tests.unit_test_cases_python_objects import PythonObjectsRepoTestCase
from eventsourcing.tests.unit_test_cases_sqlalchemy import SQLAlchemyRepoTestCase


class Sequence(EventSourcedEntity):
    class Started(EventSourcedEntity.Created):
        """Occurs when sequence is started."""

    class Appended(DomainEvent):
        """Occurs when item is appended."""

    @property
    def name(self):
        return self.id

    def append(self, item):
        stored_entity_id = self._repo.event_player.make_stored_entity_id(self.name)
        last_event = self._repo.event_store.get_most_recent_event(stored_entity_id)
        next_version = last_event.entity_version + 1
        event = Sequence.Appended(
            entity_id=self.name,
            entity_version=next_version,
            item=item,
        )
        publish(event)

    def __getitem__(self, item):
        assert isinstance(item, (six.integer_types, slice))
        assert isinstance(self._repo.event_player, EventPlayer)
        stored_entity_id = self._repo.event_player.make_stored_entity_id(self.name)
        if isinstance(item, six.integer_types):
            if item < 0:
                raise IndexError('Negative indexes are not supported')
            try:
                entity_version = self._repo.event_store.get_entity_version(stored_entity_id, item)
            except EntityVersionDoesNotExist:
                raise IndexError("Entity version not found for index: {}".format(item))
            assert isinstance(entity_version, EntityVersion)
            event_id = entity_version.event_id
            events = self._repo.event_player.event_store.get_entity_events(stored_entity_id, after=event_id, limit=1)
            events = list(events)
            if len(events) == 0:
                raise IndexError("Entity version not found for index: {}".format(item))
            return events[0].item
        elif isinstance(item, slice):
            assert item.step == None, "Slice step must be 1: {}".format(str(item.step))
            if item.start is None:
                start_index = 0
            elif item.start < 0:
                raise IndexError('Negative indexes are not supported')
            else:
                start_index = item.start

            if item.stop is None:
                limit = None
            elif item.stop < 0:
                raise IndexError('Negative indexes are not supported: {}'.format(item.stop))
            else:
                limit = item.stop - item.start

            start_version = self._repo.event_store.get_entity_version(stored_entity_id, start_index)
            start_event_id = start_version.event_id

            events = self._repo.event_player.event_store.get_entity_events(stored_entity_id,
                                                                           after=start_event_id,
                                                                           limit=limit)
            items = [e.item for e in events]
            return items

    def __len__(self):
        stored_entity_id = self._repo.event_player.make_stored_entity_id(self.name)
        event = self._repo.event_store.get_most_recent_event(stored_entity_id)
        return event.entity_version


def start_sequence(name, repo):
    event = Sequence.Started(entity_id=name)
    entity = Sequence.mutate(event=event)
    publish(event)
    entity._repo = repo
    return entity


class SequenceRepository(EntityRepository):
    pass


class SequenceRepo(EventSourcedRepository, SequenceRepository):
    domain_class = Sequence

    def get_entity(self, entity_id, until=None):
        # Replay domain events.
        sequence = self.event_player.replay_events(entity_id, limit=1)
        if sequence is not None:
            sequence._repo = self
        return sequence


class SequenceTestCase(AppishTestCase):

    def test(self):
        repo = SequenceRepo(self.event_store)

        # Start a new sequence.
        name = 'sequence1'
        sequence = start_sequence(name, repo)
        self.assertIsInstance(sequence, Sequence)

        # Append some items.
        sequence.append('item1')
        sequence.append('item2')
        sequence.append('item3')

        # Check the sequence in the repo.
        sequence = repo[name]
        self.assertIsInstance(sequence, Sequence)
        self.assertEqual(sequence.name, name)
        self.assertEqual(sequence.version, 1)

        # Check the sequence indexing.
        self.assertEqual(sequence[0], 'item1')
        self.assertEqual(sequence[1], 'item2')
        self.assertEqual(sequence[2], 'item3')

        # Check slices also work.
        self.assertEqual(sequence[0:], ['item1', 'item2', 'item3'])
        self.assertEqual(sequence[0:3], ['item1', 'item2', 'item3'])
        self.assertEqual(sequence[0:2], ['item1', 'item2'])
        self.assertEqual(sequence[0:1], ['item1'])
        self.assertEqual(sequence[1:], ['item2', 'item3'])
        self.assertEqual(sequence[1:3], ['item2', 'item3'])
        self.assertEqual(sequence[1:2], ['item2'])
        self.assertEqual(sequence[1:1], [])
        self.assertEqual(sequence[2:], ['item3'])
        self.assertEqual(sequence[2:3], ['item3'])
        self.assertEqual(sequence[3:], [])
        self.assertEqual(sequence[3:3], [])
        self.assertEqual(sequence[0:300], ['item1', 'item2', 'item3'])
        self.assertEqual(sequence[2:1], [])

        # Check iterator.
        for i, item in enumerate(sequence):
            self.assertEqual(item, 'item{}'.format(i+1))

        # Check len.
        self.assertEqual(len(sequence), 3)

        # Check index errors.
        with self.assertRaises(IndexError):
            sequence[3]

        with self.assertRaises(IndexError):
            sequence[4]

        with self.assertRaises(IndexError):
            sequence[-1]

        with self.assertRaises(IndexError):
            sequence[-2:-1]

        with self.assertRaises(IndexError):
            sequence[-1:0]

        with self.assertRaises(IndexError):
            sequence[0:-1]



class TestPythonObjectsSequence(PythonObjectsRepoTestCase, SequenceTestCase):
    pass


class TestCassandraSequence(CassandraRepoTestCase, SequenceTestCase):
    pass


class TestSQLAlchemySequence(SQLAlchemyRepoTestCase, SequenceTestCase):
    pass
